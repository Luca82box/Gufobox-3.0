VALID_AGE_GROUPS = {"bambino", "ragazzo", "adulto"}

VALID_ACTIVITY_MODES = {
    "teaching_general",
    "quiz",
    "math",
    "animal_sounds_games",
    "interactive_story",
    "foreign_languages",
    "free_conversation",
    "school_conversation",
    # New child experience activity modes
    "imitate_me",
    "logic_games",
    "personalized_story",
}

# Maps age_profile (age-range string) → canonical age_group
# Used by parental control and new experience modes
AGE_PROFILE_TO_GROUP = {
    "3-5":  "bambino",
    "6-8":  "bambino",
    "9-12": "ragazzo",
    "14+":  "adulto",
}

VALID_AGE_PROFILES = set(AGE_PROFILE_TO_GROUP.keys())

VALID_LANGUAGE_TARGETS = {
    "english",
    "spanish",
    "german",
    "french",
    "japanese",
    "chinese",
}
