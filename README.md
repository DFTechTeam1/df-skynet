# DF-SKYNET

A SaaS backend for generating **images and videos with AI**, powered by [OpenRouter](https://openrouter.ai).

## What it does

You send a prompt (text description), and the service returns an AI-generated image or video. OpenRouter handles routing the request to the right AI model behind the scenes, so the app can support many models without being locked into one provider.

## Status

Early-stage backend. The API framework, error handling, rate limiting, and multi-language support are in place; OpenRouter integration and the image/video generation endpoints are in progress.

## Running it locally

```bash
sh script/setup.sh                  # installs dependencies
sh script/run_server.sh --env dev   # starts the server on http://localhost:10000
```
