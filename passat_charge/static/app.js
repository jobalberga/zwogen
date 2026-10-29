"use strict";
const $ = (id) => document.getElementById(id);
const activeStates = new Set(["pending_stop", "confirm_stop", "scheduled", "pending_start", "confirm_start"]);
const csrf = document.querySelector('meta[name="csrf-token"]').content;
const time = new Intl.DateTimeFormat("nl-NL", { hour: "2-digit", minute: "2-digit", timeZone: "Europe/Amsterdam" });
const day = new Intl.DateTimeFormat("nl-NL", { day: "numeric", month: "long", timeZone: "Europe/Amsterdam" });
let state = null;
let sending = false;
let loading = false;
let connected = false;

function text(id, value) { $(id).textContent = value; }
function render(data) {
  state = data;
  const v = data.vehicle;
  const p = data.plan;
  const active = p && activeStates.has(p.state);
  const fresh = v.measured_at !== null && data.now - v.measured_at >= -60 && data.now - v.measured_at <= 900;
  const refreshed = data.last_refresh !== null && data.now - data.last_refresh <= 300;
  const canPlan = connected && !sending && !active && !data.busy && data.configured && data.worker_ok && v.available && fresh && refreshed && v.plugged === true;
  const target = active ? p.due : data.target;
  text("today", day.format(new Date(data.now * 1000)));
  text("target-time", time.format(new Date(target * 1000)));
  text("plan-subtitle", day.format(new Date(target * 1000)));
  text("battery", v.battery === null ? "—" : String(Math.round(v.battery)));
  const percent = document.createElement("span"); percent.textContent = "%"; $("battery").append(percent);
  text("plug", v.plugged === true ? "Aangesloten" : v.plugged === false ? "Losgekoppeld" : "Onbekend");
  text("charging", v.charging === true ? "Aan het laden" : v.charging === false ? "Gepauzeerd" : "Onbekend");
  text("vehicle-status", v.available ? (fresh ? "Verbonden met Volkswagen" : "VW-status is verouderd") : v.message);
  $("vehicle-dot").classList.toggle("online", v.available && fresh && refreshed && connected);
  text("updated", v.measured_at === null ? "" : "Auto: " + time.format(new Date(v.measured_at * 1000)));

  let message = "De app vraagt het laden nu te pauzeren en om 00:00 te starten.";
  let label = "Eenmalig laden vanaf 00:00";
  let warning = false;
  if (!data.configured) {
    message = "Volkswagen-account nog niet gekoppeld.";
    label = "Auto nog niet gekoppeld";
  } else if (!data.worker_ok) {
    message = "Planner niet bereikbaar. Controleer of de server actief is.";
    label = "Planner niet beschikbaar"; warning = true;
  } else if (!v.available) {
    message = v.message; label = "Wachten op Volkswagen";
  } else if (!fresh || !refreshed) {
    message = "Laadstatus verouderd. Ververs de auto in de VW-app.";
    label = "Wachten op actuele status";
  } else if (v.plugged !== true) {
    message = "Sluit de laadkabel aan en wacht op de VW-status.";
    label = "Sluit eerst je laadkabel aan";
  }
  if (p) {
    const descriptions = {
      pending_stop: ["Planning opgeslagen. Pauze wordt aangevraagd bij Volkswagen.", "Pauze aanvragen…"],
      confirm_stop: ["Pauze aangevraagd. Nog niet bevestigd door de auto.", "Pauze nog niet bevestigd"],
      scheduled: ["Laadpauze bevestigd. Start gepland op " + day.format(new Date(p.due * 1000)) + " om " + time.format(new Date(p.due * 1000)) + ".", "Start ingepland"],
      pending_start: ["Start wordt aangevraagd bij Volkswagen.", "Start aanvragen…"],
      confirm_start: ["Startopdracht verzonden. Nog niet bevestigd door de auto.", "Start nog niet bevestigd"],
    };
    if (active) {
      [message, label] = descriptions[p.state];
      if (p.error) { message = p.error + " Nieuwe poging volgt."; warning = true; }
      if (!data.worker_ok) { message = "Planning opgeslagen, maar planner niet bereikbaar. Controleer de server en de VW-app."; warning = true; }
      else if (!v.available) { message += " Actuele VW-status niet beschikbaar."; warning = true; }
    } else if (["failed", "expired"].includes(p.state)) {
      message = p.error; warning = true;
    } else if (p.state === "cancelled") {
      message = "Planning geannuleerd. Laden is niet hervat; dat kan via de VW-app.";
    } else if (p.state === "started") {
      message = "Laden bevestigd om " + time.format(new Date(p.updated * 1000)) + ". Opdracht afgerond.";
    }
  }
  text("plan-message-text", message);
  $("plan-message").classList.toggle("warning", warning);
  text("button-label", sending ? "Opdracht versturen…" : label);
  $("plan-button").disabled = !canPlan;
  $("cancel-button").hidden = !active;
  $("cancel-button").disabled = sending || !connected || data.busy;
}

async function refresh() {
  if (loading) return;
  loading = true;
  try {
    const response = await fetch("/api/status", { cache: "no-store", signal: AbortSignal.timeout(12000) });
    if (response.status === 401) { window.location.replace("/"); return; }
    if (!response.ok) throw new Error("Status ophalen mislukt");
    const data = await response.json();
    connected = true;
    $("connection-error").hidden = true;
    render(data);
  } catch {
    connected = false;
    $("connection-error").hidden = false;
    $("plan-button").disabled = true;
    $("cancel-button").disabled = true;
    $("vehicle-dot").classList.remove("online");
  } finally { loading = false; }
}

async function action(path) {
  if (sending) return;
  sending = true;
  $("action-result").hidden = true;
  if (state) render(state);
  try {
    // Never automatically retry a timed-out POST; its result may already exist.
    const response = await fetch(path, { method: "POST", headers: { "X-CSRF-Token": csrf }, signal: AbortSignal.timeout(12000) });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Opdracht mislukt.");
  } catch (error) {
    text("action-result", error.name === "TimeoutError" || error.name === "TypeError"
      ? "Geen bevestiging ontvangen. Controleer de planning voor een nieuwe poging."
      : error.message);
    $("action-result").hidden = false;
  } finally {
    sending = false;
    await refresh();
  }
}

$("plan-button").addEventListener("click", () => action("/api/plan"));
$("cancel-button").addEventListener("click", () => {
  const plan = state?.plan;
  if (plan && window.confirm("Planning annuleren? Het laden wordt niet hervat. Hervat zo nodig via de VW-app.")) {
    action("/api/plan/" + encodeURIComponent(plan.id) + "/cancel");
  }
});
document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(); });
window.addEventListener("online", refresh);
refresh();
setInterval(() => { if (!document.hidden) refresh(); }, 5000);
