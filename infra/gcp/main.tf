terraform {
  required_version = ">= 1.6"
  required_providers {
    google      = { source = "hashicorp/google", version = "~> 7.0" }
    google-beta = { source = "hashicorp/google-beta", version = "~> 7.0" }
  }
}

variable "project_id" { type = string }
variable "region" {
  type    = string
  default = "europe-west1"
}
variable "deploy_services" {
  type    = bool
  default = false
}
variable "image" {
  type    = string
  default = ""
}

provider "google" {
  project = var.project_id
  region  = var.region
}

provider "google-beta" {
  project = var.project_id
  region  = var.region
}

locals {
  apis = toset([
    "run.googleapis.com", "firestore.googleapis.com", "cloudtasks.googleapis.com",
    "cloudscheduler.googleapis.com", "secretmanager.googleapis.com", "iam.googleapis.com",
    "cloudbuild.googleapis.com", "artifactregistry.googleapis.com", "storage.googleapis.com",
  ])
  audience = "https://passat-worker.${var.project_id}.internal"
  common_env = {
    PASSAT_PROJECT       = var.project_id
    PASSAT_REGION        = var.region
    TASK_QUEUE           = google_cloud_tasks_queue.charging.name
    TASK_SERVICE_ACCOUNT = google_service_account.runtime["task"].email
    TASK_AUDIENCE        = local.audience
  }
}

resource "google_project_service" "apis" {
  for_each           = local.apis
  service            = each.key
  disable_on_destroy = false
}

resource "google_project_service_identity" "agents" {
  provider = google-beta
  for_each = {
    "cloudtasks.googleapis.com"     = "roles/cloudtasks.serviceAgent"
    "cloudscheduler.googleapis.com" = "roles/cloudscheduler.serviceAgent"
    "cloudbuild.googleapis.com"     = "roles/cloudbuild.serviceAgent"
    "run.googleapis.com"            = "roles/run.serviceAgent"
  }
  project    = var.project_id
  service    = each.key
  depends_on = [google_project_service.apis]
}

resource "google_project_iam_member" "agents" {
  for_each = google_project_service_identity.agents
  project  = var.project_id
  role = {
    "cloudtasks.googleapis.com"     = "roles/cloudtasks.serviceAgent"
    "cloudscheduler.googleapis.com" = "roles/cloudscheduler.serviceAgent"
    "cloudbuild.googleapis.com"     = "roles/cloudbuild.serviceAgent"
    "run.googleapis.com"            = "roles/run.serviceAgent"
  }[each.key]
  member = "serviceAccount:${each.value.email}"
}

resource "google_service_account" "runtime" {
  for_each     = toset(["web", "worker", "task", "builder"])
  account_id   = "passat-${each.key}"
  display_name = "Passat ${each.key}"
  depends_on   = [google_project_service.apis]
}

resource "google_project_iam_member" "database" {
  for_each = toset(["web", "worker"])
  project  = var.project_id
  role     = "roles/datastore.user"
  member   = "serviceAccount:${google_service_account.runtime[each.key].email}"
}

resource "google_firestore_database" "app" {
  project                 = var.project_id
  name                    = "(default)"
  location_id             = var.region
  type                    = "FIRESTORE_NATIVE"
  delete_protection_state = "DELETE_PROTECTION_ENABLED"
  deletion_policy         = "ABANDON"
  depends_on              = [google_project_service.apis]
}

resource "google_storage_bucket" "tokens" {
  name                        = "${var.project_id}-passat-tokens"
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  depends_on                  = [google_project_service.apis]
}

resource "google_storage_bucket_iam_member" "worker_tokens" {
  bucket = google_storage_bucket.tokens.name
  role   = "roles/storage.objectUser"
  member = "serviceAccount:${google_service_account.runtime["worker"].email}"
}

resource "google_storage_bucket" "build" {
  name                        = "${var.project_id}-passat-build"
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  lifecycle_rule {
    condition { age = 7 }
    action { type = "Delete" }
  }
  depends_on = [google_project_service.apis]
}

resource "google_storage_bucket_iam_member" "builder" {
  bucket = google_storage_bucket.build.name
  role   = "roles/storage.objectUser"
  member = "serviceAccount:${google_service_account.runtime["builder"].email}"
}

resource "google_artifact_registry_repository" "app" {
  location      = var.region
  repository_id = "passat"
  format        = "DOCKER"
  cleanup_policies {
    id     = "retain-recent"
    action = "KEEP"
    most_recent_versions { keep_count = 3 }
  }
  cleanup_policies {
    id     = "remove-old"
    action = "DELETE"
    condition { older_than = "604800s" }
  }
  depends_on = [google_project_service.apis]
}

resource "google_artifact_registry_repository_iam_member" "builder" {
  location   = var.region
  repository = google_artifact_registry_repository.app.name
  role       = "roles/artifactregistry.writer"
  member     = "serviceAccount:${google_service_account.runtime["builder"].email}"
}

resource "google_secret_manager_secret" "config" {
  for_each  = toset(["web", "vw"])
  secret_id = "passat-${each.key}"
  replication {
    user_managed {
      replicas { location = var.region }
    }
  }
  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_iam_member" "reader" {
  for_each  = { web = "web", vw = "worker" }
  secret_id = google_secret_manager_secret.config[each.key].id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.runtime[each.value].email}"
}

resource "google_cloud_tasks_queue" "charging" {
  name     = "passat-charging"
  location = var.region
  rate_limits {
    max_concurrent_dispatches = 1
    max_dispatches_per_second = 1
  }
  retry_config {
    max_attempts       = 8
    max_retry_duration = "3600s"
    min_backoff        = "30s"
    max_backoff        = "300s"
    max_doublings      = 4
  }
  depends_on = [google_project_service.apis]
}

resource "google_cloud_tasks_queue_iam_member" "enqueue" {
  for_each = toset(["web", "worker"])
  name     = google_cloud_tasks_queue.charging.name
  location = var.region
  role     = "roles/cloudtasks.enqueuer"
  member   = "serviceAccount:${google_service_account.runtime[each.key].email}"
}

resource "google_service_account_iam_member" "task_identity" {
  for_each           = toset(["web", "worker"])
  service_account_id = google_service_account.runtime["task"].name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.runtime[each.key].email}"
}

resource "google_cloud_run_v2_service" "worker" {
  count               = var.deploy_services ? 1 : 0
  name                = "passat-worker"
  location            = var.region
  deletion_protection = false
  custom_audiences    = [local.audience]
  template {
    service_account                  = google_service_account.runtime["worker"].email
    timeout                          = "240s"
    max_instance_request_concurrency = 1
    scaling {
      min_instance_count = 0
      max_instance_count = 1
    }
    containers {
      image = var.image
      resources {
        limits   = { cpu = "1", memory = "512Mi" }
        cpu_idle = true
      }
      dynamic "env" {
        for_each = merge(local.common_env, {
          PASSAT_MODE           = "cloud-worker"
          PASSAT_VW_SECRET_FILE = "/secrets/vw/config.json"
          TOKEN_BUCKET          = google_storage_bucket.tokens.name
        })
        content {
          name  = env.key
          value = env.value
        }
      }
      volume_mounts {
        name       = "vw-config"
        mount_path = "/secrets/vw"
      }
    }
    volumes {
      name = "vw-config"
      secret {
        secret = google_secret_manager_secret.config["vw"].secret_id
        items {
          version = "latest"
          path    = "config.json"
        }
      }
    }
  }
  lifecycle {
    precondition {
      condition     = !var.deploy_services || var.image != ""
      error_message = "Build an immutable image and provide its digest before enabling services."
    }
  }
  depends_on = [google_secret_manager_secret_iam_member.reader, google_project_iam_member.database]
}

resource "google_cloud_run_v2_service_iam_member" "worker_invoker" {
  count    = var.deploy_services ? 1 : 0
  location = var.region
  name     = google_cloud_run_v2_service.worker[0].name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.runtime["task"].email}"
}

resource "google_cloud_run_v2_service" "web" {
  count               = var.deploy_services ? 1 : 0
  name                = "passat-web"
  location            = var.region
  deletion_protection = false
  template {
    service_account                  = google_service_account.runtime["web"].email
    timeout                          = "60s"
    max_instance_request_concurrency = 8
    scaling {
      min_instance_count = 0
      max_instance_count = 1
    }
    containers {
      image = var.image
      resources {
        limits   = { cpu = "1", memory = "512Mi" }
        cpu_idle = true
      }
      dynamic "env" {
        for_each = merge(local.common_env, {
          PASSAT_MODE            = "cloud-web"
          PASSAT_WEB_SECRET_FILE = "/secrets/web/config.json"
          WORKER_URL             = google_cloud_run_v2_service.worker[0].uri
        })
        content {
          name  = env.key
          value = env.value
        }
      }
      volume_mounts {
        name       = "web-config"
        mount_path = "/secrets/web"
      }
    }
    volumes {
      name = "web-config"
      secret {
        secret = google_secret_manager_secret.config["web"].secret_id
        items {
          version = "latest"
          path    = "config.json"
        }
      }
    }
  }
  depends_on = [google_secret_manager_secret_iam_member.reader, google_cloud_run_v2_service_iam_member.worker_invoker]
}

resource "google_cloud_run_v2_service_iam_member" "web_public" {
  count    = var.deploy_services ? 1 : 0
  location = var.region
  name     = google_cloud_run_v2_service.web[0].name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_cloud_scheduler_job" "recovery" {
  count            = var.deploy_services ? 1 : 0
  name             = "passat-recovery"
  region           = var.region
  schedule         = "*/3 * * * *"
  time_zone        = "Etc/UTC"
  attempt_deadline = "60s"
  http_target {
    http_method = "POST"
    uri         = "${google_cloud_run_v2_service.worker[0].uri}/tasks/reconcile"
    oidc_token {
      service_account_email = google_service_account.runtime["task"].email
      audience              = local.audience
    }
  }
  depends_on = [google_cloud_run_v2_service_iam_member.worker_invoker]
}

output "image_repository" { value = "${var.region}-docker.pkg.dev/${var.project_id}/passat/app" }
output "build_bucket" { value = google_storage_bucket.build.name }
output "builder_account" { value = google_service_account.runtime["builder"].email }
output "website_url" { value = try(google_cloud_run_v2_service.web[0].uri, null) }
output "worker_url" { value = try(google_cloud_run_v2_service.worker[0].uri, null) }
