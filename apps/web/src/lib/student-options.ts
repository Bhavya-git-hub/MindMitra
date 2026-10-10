/** The fixed vocabularies the student forms offer (the API stores whatever short labels it gets). */

export const MOOD_LABELS: Record<number, string> = {
  1: "Very low",
  2: "Low",
  3: "Okay",
  4: "Good",
  5: "Great",
};

export const ENERGY_LABELS: Record<number, string> = {
  1: "Drained",
  2: "Low",
  3: "Moderate",
  4: "Good",
  5: "Energised",
};

export const STRESS_LABELS: Record<number, string> = {
  1: "Very calm",
  2: "Calm",
  3: "Some stress",
  4: "Stressed",
  5: "Very stressed",
};

export const SLEEP_QUALITY_LABELS: Record<number, string> = {
  1: "Poor",
  2: "Restless",
  3: "Fair",
  4: "Good",
  5: "Very restful",
};

export const EMOTIONS = [
  "calm",
  "happy",
  "hopeful",
  "grateful",
  "tired",
  "anxious",
  "sad",
  "irritable",
  "lonely",
  "overwhelmed",
] as const;

export const STRESSORS = [
  "exams",
  "deadlines",
  "workload",
  "money",
  "relationships",
  "family",
  "sleep",
  "health",
  "career",
] as const;

export const GOAL_CATEGORY_LABELS: Record<string, string> = {
  sleep: "Sleep",
  movement: "Movement",
  mindfulness: "Mindfulness",
  social: "Connection",
  academic_balance: "Study balance",
  nutrition: "Nutrition",
  other: "Something else",
};

export const RESOURCE_TYPE_LABELS: Record<string, string> = {
  article: "Article",
  video: "Video",
  exercise: "Exercise",
  audio: "Audio",
  service: "Campus service",
};
