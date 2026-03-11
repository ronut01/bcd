# Data Model

## UserProfile

- `user_id`: stable primary identifier
- `display_name`: human-readable label
- `profile_summary`: compact narrative description
- `personality_signals_json`: stable traits and habits
- `long_term_preferences_json`: category and context preferences
- `onboarding_answers_json`: original cold-start answers
- `created_at`
- `updated_at`

## DecisionRequest

- `request_id`
- `user_id`
- `prompt`
- `category`
- `context_json`
- `created_at`

## DecisionOption

- `option_id`
- `request_id`
- `option_text`
- `option_metadata_json`
- `position`

## PredictionResult

- `prediction_id`
- `request_id`
- `predicted_option_id`
- `ranked_option_ids_json`
- `score_breakdown_json`
- `confidence_by_option_json`
- `explanation`
- `strategy`
- `retrieved_memory_ids_json`
- `created_at`

## ActualChoiceFeedback

- `feedback_id`
- `request_id`
- `actual_option_id`
- `reason_text`
- `reason_tags_json`
- `created_at`

## MemoryEntry

- `memory_id`
- `user_id`
- `source_request_id`
- `source_feedback_id`
- `category`
- `summary`
- `chosen_option_text`
- `context_json`
- `tags_json`
- `salience_score`
- `embedding_json`
- `created_at`

## PreferenceSnapshot

- `snapshot_id`
- `user_id`
- `summary`
- `short_term_preference_notes_json`
- `drift_markers_json`
- `derived_statistics_json`
- `created_at`
