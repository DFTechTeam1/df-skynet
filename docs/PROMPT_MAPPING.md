# Prompt Settings — MD File Mapping

Each app page/menu has its own prompt-settings file. This is the map of which file backs which page.

## Global menu

Applied everywhere in the app.

| File | Used when |
|---|---|
| `image-restyle.md` | Restyling an image |
| `image-edit.md` | Editing an image |
| `nfsw.md` | Global (NSFW) content rules |

## Chat session

| File | Used when |
|---|---|
| `chatbot.md` | System prompt of every new chat assistant session (feature `chat_assistant`, not attached to a menu) |

## Element page

| File | Asset type |
|---|---|
| `image-asset-character.md` | Character |
| `image-asset-environment.md` | Environment |
| `image-asset-object.md` | Object |
| `image-asset-style.md` | Style |

## Storyboard page

| File | Purpose |
|---|---|
| `image-story-fullgen.md` | Full image generation for a storyboard |
| `video-story-fullgen.md` | Full video generation for a storyboard |

## Gen page

| File | Purpose |
|---|---|
| `video-led-fullgen.md` | Full video generation (LED flow) |
| `image-led-fullgen.md` | Full image generation (LED flow) |
| `enhance-led-full.md` | Writing the final image / video prompt (feature `enhance_prompt`) |

> Note: these files are referenced but not yet created in this repo.
