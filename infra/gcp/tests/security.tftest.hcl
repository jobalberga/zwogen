mock_provider "google" {}
mock_provider "google-beta" {
  mock_resource "google_project_service_identity" {
    defaults = { email = "service-agent@test-project.iam.gserviceaccount.com" }
  }
}

override_resource {
  target = google_service_account.runtime["web"]
  values = { email = "passat-web@test-project.iam.gserviceaccount.com", name = "projects/test-project/serviceAccounts/passat-web@test-project.iam.gserviceaccount.com" }
}
override_resource {
  target = google_service_account.runtime["worker"]
  values = { email = "passat-worker@test-project.iam.gserviceaccount.com", name = "projects/test-project/serviceAccounts/passat-worker@test-project.iam.gserviceaccount.com" }
}
override_resource {
  target = google_service_account.runtime["task"]
  values = { email = "passat-task@test-project.iam.gserviceaccount.com", name = "projects/test-project/serviceAccounts/passat-task@test-project.iam.gserviceaccount.com" }
}
override_resource {
  target = google_service_account.runtime["builder"]
  values = { email = "passat-builder@test-project.iam.gserviceaccount.com", name = "projects/test-project/serviceAccounts/passat-builder@test-project.iam.gserviceaccount.com" }
}
override_resource {
  target = google_secret_manager_secret.config["web"]
  values = { id = "projects/test-project/secrets/passat-web" }
}
override_resource {
  target = google_secret_manager_secret.config["vw"]
  values = { id = "projects/test-project/secrets/passat-vw" }
}

run "private_worker_and_least_privilege" {
  command = apply
  variables {
    project_id      = "test-project"
    deploy_services = true
    image           = "europe-west1-docker.pkg.dev/test-project/passat/app@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  }
  assert {
    condition     = google_cloud_run_v2_service_iam_member.worker_invoker[0].member == "serviceAccount:passat-task@test-project.iam.gserviceaccount.com"
    error_message = "Only the task identity may invoke the worker."
  }
  assert {
    condition     = google_secret_manager_secret_iam_member.reader["vw"].member == "serviceAccount:passat-worker@test-project.iam.gserviceaccount.com"
    error_message = "The web service must not read Volkswagen credentials."
  }
  assert {
    condition     = google_storage_bucket_iam_member.worker_tokens.member == "serviceAccount:passat-worker@test-project.iam.gserviceaccount.com"
    error_message = "Only the worker may read the private token bucket."
  }
  assert {
    condition     = google_storage_bucket.tokens.public_access_prevention == "enforced"
    error_message = "Token bucket must prohibit public access."
  }
  assert {
    condition = (
      google_storage_bucket_iam_member.builder_bucket_reader.role == "roles/storage.legacyBucketReader" &&
      google_storage_bucket_iam_member.builder_bucket_reader.bucket == google_storage_bucket.build.name &&
      google_storage_bucket_iam_member.builder_bucket_reader.member == "serviceAccount:passat-builder@test-project.iam.gserviceaccount.com" &&
      google_storage_bucket_iam_member.builder.bucket == google_storage_bucket.build.name &&
      google_storage_bucket_iam_member.builder.role == "roles/storage.objectUser"
    )
    error_message = "The builder must read bucket metadata and build objects within the build bucket only."
  }
  assert {
    condition     = google_cloud_run_v2_service.worker[0].template[0].scaling[0].min_instance_count == 0 && google_cloud_run_v2_service.web[0].template[0].scaling[0].min_instance_count == 0
    error_message = "Both services must scale to zero."
  }
  assert {
    condition     = google_cloud_run_v2_service.worker[0].template[0].max_instance_request_concurrency == 1
    error_message = "Vehicle tasks must not execute concurrently in one instance."
  }
}
