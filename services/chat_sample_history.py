"""Static sample conversation (250 user/assistant exchanges = 500 bubbles), for testing how a long history behaves."""

from schemas.format.openrouter import Message

_EXCHANGES = [
    (
        "What does 16:9 mean for an LED wall?",
        "It is the width-to-height ratio: for every 16 units wide the screen is 9 tall. It suits most video content.",
    ),
    (
        "And 21:9?",
        "21:9 is wider, a cinematic ratio. It fits long LED walls and stage backdrops that run edge to edge.",
    ),
    (
        "Which one is better for a concert backdrop?",
        "21:9 usually, because the stage is wide. Use 16:9 if the wall is a tall centre screen.",
    ),
    (
        "How do I describe a neon city for the generator?",
        "Name the subject, time, palette and mood: 'neon city at night, wet streets, magenta and cyan lights, cinematic'.",
    ),
    (
        "Can I keep the same character across images?",
        "Yes. Generate a reference sheet first, then attach it to every later prompt.",
    ),
    (
        "What is a reference sheet?",
        "One image with the character from front, side and back, same pose and scale, so the model keeps the look.",
    ),
    (
        "How many images can I attach to one chat?",
        "The limit is set by the admin as the number of unique files per chat. A file reused counts once.",
    ),
    (
        "What happens when the chat is full?",
        "You can no longer add messages, but you can transfer the knowledge into a new chat.",
    ),
    (
        "When does transfer knowledge open?",
        "Once the chat reaches the minimum percentage of the message limit that the admin configured.",
    ),
    (
        "Does the transfer copy my images?",
        "The new chat gets a summary and the files the old chat used, so you can continue from the same point.",
    ),
    (
        "Give me a prompt for a calm beach loop.",
        "'Slow waves on a quiet beach at sunset, warm orange sky, gentle camera drift, seamless loop, 21:9'.",
    ),
    (
        "Make it moodier.",
        "'Slow waves on a deserted beach at dusk, deep teal and violet sky, low fog, soft rolling camera, seamless loop'.",
    ),
    ("Shorter please.", "'Dusk beach, slow waves, teal and violet fog, seamless loop'."),
    (
        "What size should the LED video be?",
        "Match the wall's pixel size. If you only know the aspect ratio, export at that ratio and scale on the processor.",
    ),
    (
        "Can the assistant generate the video itself?",
        "No. It writes prompts and answers questions; generation happens on the generation page.",
    ),
    (
        "Why was my last image cut off?",
        "The ratio probably did not match the wall. Choose the ratio before generating, not after.",
    ),
    ("What is a good frame rate?", "30 fps is fine for most content. Use 60 fps for fast camera moves on large walls."),
    (
        "How do I avoid banding in gradients?",
        "Add a little noise or grain, and avoid very dark, smooth gradients on LED surfaces.",
    ),
    (
        "Is brand logo use allowed?",
        "Generic objects are fine. Real brand names and logos are blocked by the content rules.",
    ),
    (
        "Why did my prompt get blocked?",
        "It likely matched a guardrail: brands, explicit content, violence against real people, or an injection attempt.",
    ),
    (
        "Can I ask about pricing of models?",
        "Yes. Each model shows its usage cost; the project also has a spend cap set by its class.",
    ),
    (
        "What happens at the spend cap?",
        "Generation and chat are refused until the limit is raised or the cycle resets.",
    ),
    (
        "Summarise what we covered.",
        "Ratios for LED walls, prompt writing, reference sheets, attachment and message limits, transfer knowledge, and guardrails.",
    ),
    ("Thanks, that helps.", "You are welcome. Ask whenever you want to plan the next visual."),
    (
        "One last thing: what is a seamless loop?",
        "A clip whose last frame matches its first, so it repeats on the wall without a visible jump.",
    ),
]

# 25 topics x 9 question styles = 225 more exchanges, deterministic so every run sends the same history
_TOPICS = [
    "LED wall resolution",
    "stage backdrop colors",
    "looping video",
    "camera movement",
    "character reference sheets",
    "lighting mood",
    "text on screen",
    "transitions",
    "storyboard scenes",
    "shot length",
    "image editing",
    "restyling a photo",
    "aspect ratios",
    "frame rate",
    "file formats",
    "color banding",
    "prompt length",
    "negative space",
    "scene continuity",
    "background music timing",
    "wide shots",
    "close-ups",
    "abstract visuals",
    "product visuals",
    "event opening video",
]
_QUESTIONS = [
    (
        "How should I think about {t}?",
        "Start from the screen and the story: decide what the audience must notice about {t}, then keep everything else quiet.",
    ),
    (
        "Give me a quick tip on {t}.",
        "Keep {t} simple and consistent across scenes; one clear choice beats several competing ones.",
    ),
    (
        "What is a common mistake with {t}?",
        "Changing {t} between shots without a reason, which makes the sequence feel unplanned.",
    ),
    (
        "Can you explain {t} in one sentence?",
        "{t} is a creative choice you fix early so later prompts and edits stay consistent.",
    ),
    (
        "How does {t} affect the final result?",
        "It sets the first impression: {t} decides how readable and how polished the visual feels on the wall.",
    ),
    (
        "Suggest a prompt idea about {t}.",
        "Describe the subject, the mood and {t} explicitly, for example: 'night scene, soft blue light, focus on {t}'.",
    ),
    (
        "What should I check before generating with {t}?",
        "Check the ratio, the length and whether {t} matches the reference files already attached to the chat.",
    ),
    (
        "How do I fix a problem with {t}?",
        "Change one thing at a time. Adjust {t} first, regenerate, and compare before touching other settings.",
    ),
    (
        "Summarise {t} for my team.",
        "{t}: choose it early, keep it consistent, and review it on the real screen before the event.",
    ),
]
_EXCHANGES += [(q.format(t=t), a.format(t=t)) for t in _TOPICS for q, a in _QUESTIONS]

SAMPLE_CONVERSATION = [
    Message.build(role, text).to_payload()
    for question, answer in _EXCHANGES
    for role, text in (("user", question), ("assistant", answer))
]
