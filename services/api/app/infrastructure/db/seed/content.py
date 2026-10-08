"""Static synthetic content pools. All text is fictional and non-clinical."""

DEPARTMENTS = [
    ("Computer Science", "CS"),
    ("Psychology", "PSY"),
    ("Mechanical Engineering", "ME"),
    ("Business Administration", "BBA"),
    ("Biological Sciences", "BIO"),
]

COURSE_TITLES = [
    "Foundations of {d}",
    "Intermediate {d}",
    "Research Methods in {d}",
]

EMOTIONS = [
    "calm",
    "hopeful",
    "tired",
    "anxious",
    "motivated",
    "overwhelmed",
    "content",
    "restless",
    "lonely",
    "grateful",
    "irritable",
    "focused",
    "sad",
    "energised",
]

MOOD_NOTES = [
    "Long lecture day but the group project is coming together.",
    "Slept badly before the quiz. Trying to take it easy tonight.",
    "Went for a walk between classes and it helped.",
    "Feeling behind on assignments, making a plan for the weekend.",
    "Good chat with a friend after lab.",
    "Hostel was noisy again, hard to concentrate.",
    "Exam in two days. Nervous but prepared.",
    "Skipped the gym, felt drained.",
    "Nice day. Finished the report early.",
]

JOURNAL_TITLES = [
    "Thoughts after class",
    "Weekend reset",
    "What worked today",
    "Exam week",
    "Small wins",
]

JOURNAL_BODIES = [
    "Today was a mix. The morning lecture dragged but the lab session went well. I want to "
    "keep a steadier routine this week, starting with a fixed bedtime.",
    "I noticed I get tense before presentations. Breathing exercises from the resource library "
    "helped a little. I will practise again tomorrow.",
    "Spent the evening with friends instead of studying and felt better for it. Planning to "
    "balance deadlines with a bit more rest.",
    "Feeling stretched across assignments. Writing down priorities made it feel more manageable.",
]

GOAL_TEMPLATES = [
    ("Sleep 7+ hours on weeknights", "sleep", "hours", 7),
    ("Walk 20 minutes a day", "movement", "minutes", 20),
    ("Practise 10 minutes of mindfulness", "mindfulness", "minutes", 10),
    ("Meet a friend weekly", "social", "meetups", 1),
    ("Finish assignments two days early", "academic_balance", "assignments", 3),
    ("Drink 2 litres of water", "nutrition", "litres", 2),
]

STRESSORS = [
    "exams",
    "deadlines",
    "finances",
    "sleep",
    "relationships",
    "housing",
    "workload",
    "career",
]

# (title, summary, type, tags, minutes)
RESOURCES = [
    (
        "Box breathing for exam nerves",
        "A 4-minute guided breathing exercise to settle before tests.",
        "exercise",
        ["breathing", "exams", "anxiety-skills"],
        4,
    ),
    (
        "Winding down before sleep",
        "Simple evening routine ideas for steadier sleep.",
        "article",
        ["sleep", "routine"],
        6,
    ),
    (
        "Planning a heavy assignment week",
        "Break big deadlines into manageable steps.",
        "article",
        ["planning", "deadlines", "stress"],
        8,
    ),
    (
        "5-minute body scan",
        "A short guided audio to notice tension and relax.",
        "audio",
        ["mindfulness", "relaxation"],
        5,
    ),
    (
        "Talking to a friend about a hard time",
        "Ways to start the conversation and what to say.",
        "article",
        ["social", "support"],
        7,
    ),
    (
        "Campus counselling centre: how to book",
        "What to expect and how to make an appointment.",
        "service",
        ["counselling", "support", "campus"],
        None,
    ),
    (
        "Movement breaks for long study days",
        "Quick stretches and walks between study blocks.",
        "video",
        ["movement", "study"],
        10,
    ),
    (
        "Grounding with the 5-4-3-2-1 method",
        "A sensory exercise to feel present when overwhelmed.",
        "exercise",
        ["grounding", "stress"],
        5,
    ),
    (
        "Saying no without guilt",
        "Setting limits when your schedule is full.",
        "article",
        ["boundaries", "workload"],
        6,
    ),
    (
        "Eating well on a student budget",
        "Practical, affordable meal ideas.",
        "article",
        ["nutrition", "budget"],
        7,
    ),
    (
        "Peer support groups on campus",
        "Find student-led groups that meet weekly.",
        "service",
        ["social", "campus", "support"],
        None,
    ),
    (
        "Journaling prompts for busy weeks",
        "Short prompts to reflect without pressure.",
        "article",
        ["journaling", "reflection"],
        5,
    ),
    (
        "Managing screen time at night",
        "Tips for a calmer evening wind-down.",
        "article",
        ["sleep", "habits"],
        5,
    ),
    (
        "Draft: stress and the first-year transition",
        "Under review by the counselling team.",
        "article",
        ["stress", "first-year"],
        9,
    ),
]

SPECIALTIES = [
    "academic stress",
    "sleep difficulties",
    "adjustment to college",
    "relationship concerns",
    "mindfulness-based approaches",
    "cognitive behavioural approaches",
    "grief and loss",
    "career and identity",
    "social connection",
]

LANGUAGES = ["English", "Hindi", "Marathi", "Tamil", "Bengali", "Gujarati", "Telugu"]

THERAPY_NOTE_SNIPPETS = [
    "SYNTHETIC NOTE. Reviewed week's routine; agreed on a fixed wake time and a short evening "
    "wind-down. Student reports slightly lower stress. Follow up on sleep log next session.",
    "SYNTHETIC NOTE. Discussed upcoming exams and a study schedule with built-in breaks. "
    "Practised a breathing exercise in session. Homework: two short practices this week.",
    "SYNTHETIC NOTE. Explored feeling disconnected from classmates. Identified one low-pressure "
    "campus group to try. Student open to a check-in message midweek.",
    "SYNTHETIC NOTE. Brief session; student tired after travel. Reviewed goals and rescheduled "
    "longer discussion. No safety concerns raised.",
]

MESSAGES_STUDENT = [
    "Hi, could we move this week's session to the afternoon if possible?",
    "I tried the breathing exercise before my quiz and it helped a bit.",
    "Thanks for the resources. I'll look at the sleep one tonight.",
    "I'm finding this week busy. Can we talk about planning next time?",
]
MESSAGES_THERAPIST = [
    "Of course, I'll check my calendar and confirm shortly.",
    "Glad it helped. Let's build on that in our next session.",
    "Happy to help. Remember the campus counselling line is open if you need it sooner.",
    "Good idea. Bring your timetable and we'll plan together.",
]

AI_USER_PROMPTS = [
    "I have three deadlines this week and I don't know where to start.",
    "Can you suggest something to help me wind down before bed?",
    "I'm nervous about a presentation tomorrow.",
    "How can I make time to see friends when I'm so busy?",
]
AI_ASSISTANT_REPLIES = [
    "That sounds like a lot. One approach is to list each deadline, pick the earliest, and break "
    "it into 30-minute steps. I'm an AI wellness companion, not a therapist; if things feel "
    "heavy, the campus counselling centre can help.",
    "A short routine can help: dim lights, put your phone away, and try a few slow breaths. "
    "There's a 'Winding down before sleep' article in the resource library.",
    "Feeling nervous before a presentation is common. Try box breathing for a few minutes, and "
    "rehearse the opening lines out loud. I can't give medical advice, but a counsellor can "
    "offer more.",
    "Small, scheduled time with friends can help, even 20 minutes. Maybe pick one fixed slot "
    "this week.",
]

CRISIS_FIXTURE_EXCERPT = (
    "[SYNTHETIC FIXTURE] Test text standing in for a distress signal. Not real student content."
)
