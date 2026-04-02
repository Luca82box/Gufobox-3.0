"""
core/wizard.py — Wizard state machine for AI category-based RFID statuettes.

Manages the guided selection flow triggered when a `school` or `entertainment`
RFID token is read.  The wizard collects:
  1. age_group     (bambino | ragazzo | adulto)
  2. activity_mode (category-specific list)
  3. language_target (only for foreign_languages)
  4. learning_step  (only for foreign_languages)

When all required steps are complete the wizard applies the resulting
edu_config to the live AI educational settings via api.ai.apply_rfid_edu_config.

The state is kept in RAM (wizard_state dict) and exposed in the public snapshot.
It is intentionally NOT persisted across reboots – a new RFID scan restarts it.
"""
import threading
from core.utils import log
from core.event_log import log_event

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
VALID_CATEGORIES = {"school", "entertainment"}
VALID_AGE_GROUPS = {"bambino", "ragazzo", "adulto"}

# Activities available per category (order matters for UI display)
CATEGORY_ACTIVITIES = {
    "school": [
        "teaching_general",
        "math",
        "foreign_languages",
        "school_conversation",
    ],
    "entertainment": [
        "quiz",
        "animal_sounds_games",
        "interactive_story",
        "free_conversation",
    ],
}

# Activities that require a language selection step
ACTIVITIES_NEEDING_LANGUAGE = {"foreign_languages"}

# Activities that require a learning_step selection
ACTIVITIES_NEEDING_STEP = {"foreign_languages"}

VALID_LANGUAGES = {"english", "spanish", "german", "french", "japanese", "chinese"}

STAGE_AGE = "age_group"
STAGE_ACTIVITY = "activity_mode"
STAGE_LANGUAGE = "language_target"
STAGE_STEP = "learning_step"
STAGE_DONE = "done"

_lock = threading.RLock()  # Reentrant lock: wizard_submit calls get_wizard_state() internally

# ---------------------------------------------------------------------------
# In-memory state
# ---------------------------------------------------------------------------
wizard_state = {
    "active": False,
    "source_category": None,       # "school" | "entertainment"
    "source_rfid": None,           # RFID code that triggered the wizard
    "current_stage": None,         # age_group | activity_mode | language_target | learning_step | done
    "partial_selection": {},       # accumulated selections so far
    "current_options": [],         # list of valid options for the current stage
    "completed_config": None,      # final edu_config dict when stage==done
    "error": None,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _get_configured_activities(category: str) -> list:
    """
    Return the list of activity IDs for *category* from the admin-configured
    wizard categories stored in ai_settings["wizard_categories"].

    Only activities with ``enabled = True`` are included.
    The order matches the admin-saved order.

    Falls back to the hardcoded ``CATEGORY_ACTIVITIES`` defaults when:
    - the admin config is absent or not a dict
    - the category entry is missing
    - no activity is enabled
    - any other unexpected error
    """
    default = list(CATEGORY_ACTIVITIES.get(category, []))
    try:
        # Late import to avoid circular dependency
        from api.ai import ai_settings  # noqa: PLC0415
        wizard_cats = ai_settings.get("wizard_categories")
        if not isinstance(wizard_cats, dict):
            return default
        cat_data = wizard_cats.get(category)
        if not isinstance(cat_data, dict):
            return default
        activities = cat_data.get("activities")
        if not isinstance(activities, list):
            return default
        enabled = [
            act["id"]
            for act in activities
            if (
                isinstance(act, dict)
                and isinstance(act.get("id"), str)
                and act["id"]
                and act.get("enabled", True)
            )
        ]
        return enabled if enabled else default
    except (AttributeError, KeyError, TypeError):  # defensive: config corruption
        return default


def _options_for_stage(stage, partial):
    """Return the list of valid option strings for the given stage."""
    if stage == STAGE_AGE:
        return sorted(VALID_AGE_GROUPS)
    if stage == STAGE_ACTIVITY:
        cat = partial.get("source_category")
        return _get_configured_activities(cat)
    if stage == STAGE_LANGUAGE:
        return sorted(VALID_LANGUAGES)
    if stage == STAGE_STEP:
        return [str(i) for i in range(1, 11)]
    return []


def _next_stage(current_stage, partial):
    """Determine the next stage given the current one and accumulated selections."""
    if current_stage == STAGE_AGE:
        return STAGE_ACTIVITY
    if current_stage == STAGE_ACTIVITY:
        act = partial.get("activity_mode", "")
        if act in ACTIVITIES_NEEDING_LANGUAGE:
            return STAGE_LANGUAGE
        return STAGE_DONE
    if current_stage == STAGE_LANGUAGE:
        act = partial.get("activity_mode", "")
        if act in ACTIVITIES_NEEDING_STEP:
            return STAGE_STEP
        return STAGE_DONE
    if current_stage == STAGE_STEP:
        return STAGE_DONE
    return STAGE_DONE


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def wizard_start(source_category: str, source_rfid: str = None) -> dict:
    """
    Start the wizard for the given category.

    Returns the wizard state dict (a snapshot, not the live object).
    """
    if source_category not in VALID_CATEGORIES:
        return {"error": f"Categoria non valida: '{source_category}'. Valori: {sorted(VALID_CATEGORIES)}"}

    with _lock:
        partial = {"source_category": source_category}
        stage = STAGE_AGE
        wizard_state.update({
            "active": True,
            "source_category": source_category,
            "source_rfid": source_rfid,
            "current_stage": stage,
            "partial_selection": partial,
            "current_options": _options_for_stage(stage, partial),
            "completed_config": None,
            "error": None,
        })

    log(f"Wizard avviato: categoria={source_category} rfid={source_rfid}", "info")
    log_event("wizard", "info", "Wizard avviato", {
        "category": source_category,
        "rfid": source_rfid,
    })
    return get_wizard_state()


def wizard_submit(answer: str) -> dict:
    """
    Submit an answer for the current wizard stage.

    answer — the selected option (string).
    Returns updated wizard state dict, or dict with 'error' key on failure.
    """
    with _lock:
        if not wizard_state.get("active"):
            return {"error": "Nessun wizard attivo. Avvicina una statuina per iniziare."}

        stage = wizard_state["current_stage"]
        if stage == STAGE_DONE:
            return {"error": "Il wizard è già completato."}

        options = wizard_state["current_options"]
        if options and answer not in options:
            return {
                "error": f"Risposta non valida: '{answer}'. Opzioni: {options}",
                "wizard": get_wizard_state(),
            }

        partial = wizard_state["partial_selection"].copy()

        # Store the answer in partial
        if stage == STAGE_AGE:
            partial["age_group"] = answer
        elif stage == STAGE_ACTIVITY:
            partial["activity_mode"] = answer
        elif stage == STAGE_LANGUAGE:
            partial["language_target"] = answer
        elif stage == STAGE_STEP:
            try:
                partial["learning_step"] = max(1, int(answer))
            except (ValueError, TypeError):
                partial["learning_step"] = 1

        next_stage = _next_stage(stage, partial)
        partial_for_options = partial.copy()

        wizard_state["partial_selection"] = partial
        wizard_state["current_stage"] = next_stage
        wizard_state["current_options"] = _options_for_stage(next_stage, partial_for_options)

        if next_stage == STAGE_DONE:
            wizard_state["active"] = False
            completed = _build_completed_config(partial)
            wizard_state["completed_config"] = completed
            log(f"Wizard completato: {completed}", "info")
            log_event("wizard", "info", "Wizard completato", {"config": completed})
            return get_wizard_state()

    return get_wizard_state()


def wizard_cancel() -> dict:
    """Cancel (reset) the current wizard."""
    with _lock:
        wizard_state.update({
            "active": False,
            "source_category": None,
            "source_rfid": None,
            "current_stage": None,
            "partial_selection": {},
            "current_options": [],
            "completed_config": None,
            "error": None,
        })
    log("Wizard annullato", "info")
    return get_wizard_state()


def get_wizard_state() -> dict:
    """Return a snapshot copy of the current wizard state (thread-safe)."""
    with _lock:
        import copy
        return copy.deepcopy(wizard_state)


def wizard_apply_config() -> tuple:
    """
    Apply the completed wizard config to the live AI educational settings.

    Returns (success: bool, message: str).
    Must be called after wizard reaches STAGE_DONE.
    """
    state = get_wizard_state()
    config = state.get("completed_config")
    if not config:
        return False, "Nessuna configurazione completata da applicare"

    try:
        from api.ai import apply_rfid_edu_config
        apply_rfid_edu_config(config)
        log(f"Wizard config applicata: {config}", "info")
        log_event("wizard", "info", "Config wizard applicata all'AI educativa", {"config": config})
        return True, "Configurazione applicata con successo"
    except Exception as e:
        log(f"Errore applicazione config wizard: {e}", "warning")
        log_event("wizard", "error", "Errore applicazione config wizard", {"error": str(e)})
        return False, f"Errore applicazione config: {e}"


def _build_completed_config(partial: dict) -> dict:
    """Build the final edu_config from accumulated partial selections."""
    return {
        "age_group": partial.get("age_group", "bambino"),
        "activity_mode": partial.get("activity_mode", "free_conversation"),
        "language_target": partial.get("language_target", "english"),
        "learning_step": partial.get("learning_step", 1),
    }
