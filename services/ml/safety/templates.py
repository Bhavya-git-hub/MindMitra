"""Fixed replies used instead of a model reply.

These are written once, reviewed, and never generated. Crisis replies are not here: the API
composes those itself, next to the institution's crisis contacts, because it must be able to
send them even when this service is down.
"""

from typing import Final

DISCLAIMER: Final = (
    "I'm an AI wellness companion, not a therapist. I can't diagnose or give medical advice, "
    "and I can make mistakes. If you're in danger, use Get help now."
)

DIAGNOSIS_REQUEST: Final = (
    "That's a really understandable thing to wonder about. I'm an AI, so I can't diagnose "
    "anything or tell you whether you have a condition. A counsellor or doctor can talk it "
    "through with you properly, and you can book a counsellor from Talk to a therapist. In the "
    "meantime, if you'd like to tell me what's been going on lately, we can think about what "
    "might help day to day."
)

MEDICATION_REQUEST: Final = (
    "I can't give advice about medication, supplements or doses, including whether to start, "
    "stop or change anything. A doctor or pharmacist is the right person for that, and a "
    "counsellor can help you think about what to ask them. If something is bothering you "
    "right now, I'm happy to talk it through or share some ideas that don't involve medication."
)

PROMPT_INJECTION: Final = (
    "I can't change how I work or pretend to be someone else. I'm an AI wellness companion, "
    "here to listen and help you think things through. What's on your mind today?"
)

SAFE_FALLBACK: Final = (
    "Thanks for telling me that. I want to make sure I respond well, so let me keep this "
    "simple: what you're going through matters. Could you tell me a little more about what's "
    "been hardest? If it would help to talk to a person, you can book a counsellor from Talk "
    "to a therapist."
)

UNAVAILABLE: Final = (
    "I'm having trouble replying right now. Please try again in a little while. If you need "
    "to talk to someone now, use Get help now, or book a counsellor from Talk to a therapist."
)

HUMAN_SUPPORT_NUDGE: Final = (
    "We've talked about this for a while now. A counsellor could help with it in ways I "
    "can't, and you can book one from Talk to a therapist whenever you're ready."
)
