# Tool Routing Reference

Per-tool prompt-formatting rules. Read only the section matching the user's
target tool. Fill-in template structures live in [templates.md](templates.md).

---

## Claude (claude.ai, Claude API, Claude 4.x)

Durable across Claude 4.x:
- Be explicit and specific — Claude 4.x follows instructions literally; missing context yields narrow literal output, not a smart guess.
- Opus 4.x over-engineers by default — add "Only make changes directly requested. Do not add features or refactor beyond what was asked."
- XML tags help for complex multi-section prompts: `<context>`, `<task>`, `<constraints>`, `<output_format>`.
- Provide the WHY, not just the WHAT — Claude generalizes better from explanations.
- Always specify output format and length explicitly.
- Complex/multi-step: front-load everything in one turn — intent, constraints, acceptance criteria, relevant files.
- Do NOT add "think step by step" or thinking budgets — recent Opus uses adaptive thinking. To influence depth: "Think carefully before responding" (more) or "Prioritize responding quickly" (less).
- Use Template M (templates.md) for agentic or multi-step tasks.
- Recent Opus (4.7/4.8) is more literal than 4.6 — vague first turns produce narrower results. 4.8 has a 1M-token context window; large multi-file context can go in one prompt, but padding still dilutes attention.

## ChatGPT / GPT-5.x / OpenAI GPT models

- Start with the smallest prompt that achieves the goal — add structure only when needed.
- Be explicit about the output contract: format, length, what "done" looks like.
- State tool-use expectations explicitly if the model has tools.
- Compact structured output works — GPT-5.x handles dense instruction well.
- Constrain verbosity when needed: "Respond in under 150 words. No preamble. No caveats."
- Strong at long-context synthesis and tone adherence — leverage these.

## o3 / o4-mini / OpenAI reasoning models

- SHORT clean instructions ONLY — these reason across thousands of internal tokens.
- NEVER add CoT, "think step by step", or reasoning scaffolding — it degrades output.
- Prefer zero-shot; add few-shot only if strictly needed and tightly aligned.
- State what you want and what done looks like. Nothing more.
- Keep system prompts under ~200 words.

## Gemini 2.x / Gemini 3 Pro

- Strong at long-context and multimodal — leverage for document-heavy prompts.
- Prone to hallucinated citations — add "Cite only sources you are certain of. If uncertain, say [uncertain]."
- Can drift from strict formats — use explicit format locks with a labelled example.
- For grounded tasks: "Base your response only on the provided context. Do not extrapolate."

## Qwen 2.5 (instruct)

- Excellent instruction following, JSON output, structured data.
- Clear system prompt defining the role helps.
- Explicit output format specs (incl. JSON schemas) work well.
- Shorter focused prompts outperform long complex ones.

## Qwen3 (thinking mode)

- Thinking mode (`/think` / `enable_thinking=True`): treat like o3 — short clean instructions, no CoT.
- Non-thinking mode: treat like Qwen2.5 instruct — full structure, explicit format, role assignment.

## Ollama (local models)

- ALWAYS ask which model is running — Llama3, Mistral, Qwen2.5, CodeLlama behave differently.
- System prompt is the biggest lever — include it so the user can set it in their Modelfile.
- Shorter simpler prompts; local models lose coherence with deep nesting.
- Temperature 0.1 for coding/deterministic, 0.7–0.8 for creative.
- Coding: prefer CodeLlama or Qwen2.5-Coder over general Llama.

## Llama / Mistral / open-weight LLMs

- Shorter prompts, simple flat structure, no deep nesting.
- Be more explicit than with Claude/GPT — instruction following is weaker.
- Always include a role in the system prompt.

## DeepSeek-R1

- Reasoning-native — do NOT add CoT.
- Short clean instructions: goal + desired output format.
- Outputs reasoning in `<think>` tags — add "Output only the final answer, no reasoning." if needed.

## MiniMax (M3 / M2.7)

- OpenAI-compatible API — GPT-style prompts transfer directly.
- Strong instruction following, structured output, long context (1M on M2.7); M2.7-highspeed for latency-sensitive work.
- Temperature must be 0–1 inclusive.
- May emit `<think>` tags — add "Output only the final answer, no reasoning tags." if unwanted.
- Supports OpenAI-style tool definitions for function calling.

## Claude Code

- Agentic: starting state + target state + allowed actions + forbidden actions + stop conditions + checkpoints. Stop conditions are MANDATORY.
- Do NOT hardcode effort levels or thinking budgets — the harness manages depth on current Opus.
- Recent Opus is literal — front-load intent, file scope, constraints, acceptance criteria, session strategy.
- Uses fewer tool calls / subagents by default — instruct explicitly when needed ("Read all files in /src/auth/ before starting"; "Use a subagent to investigate X").
- Add anti-over-engineering line; always scope to specific files/directories.
- Human review triggers: "Stop and ask before deleting any file, adding any dependency, or affecting the database schema."
- Session hygiene: new task = new session; /rewind instead of mid-conversation corrections; /compact at ~50% context.
- Complex tasks: use Template M.

## Antigravity (Google's agent-first IDE, Gemini 3 Pro)

- Task-based prompting — describe outcomes, not steps.
- Prompt for an Artifact (task list / plan) before execution for review.
- Include browser-verification steps ("verify UI at 375px and 1440px").
- Specify autonomy level ("Ask before running destructive terminal commands").
- One deliverable per session — don't mix tasks.

## Cursor / Windsurf

- File path + function name + current behavior + desired change + do-not-touch list + language/version.
- Never a global instruction without a file anchor.
- "Done when:" is required — defines when the agent stops editing.
- Complex tasks: split into sequential prompts. Use Template G.

## Cline

- Agentic VS Code extension; match prompting style to the underlying model.
- Starting state + target state + file scope + stop conditions + approval gates.
- Specify which files to edit and which to leave untouched.
- Add "Ask before running terminal commands / installing dependencies."
- Multi-step: sequential prompts with clear checkpoints; review Cline's task list before it executes.

## GitHub Copilot

- Write the exact function signature, docstring, or comment immediately before invoking.
- Describe input types, return type, edge cases, and what the function must NOT do.
- Copilot completes what it predicts, not what you intend — leave no ambiguity.

## Bolt / v0 / Lovable / Figma Make / Google Stitch

- Full-stack generators default to bloat — scope down explicitly: stack, version, what NOT to scaffold, component boundaries.
- Lovable: design-forward descriptions with visual/UX intent.
- v0: Vercel-native — specify if you need non-Next.js output.
- Bolt: be explicit about frontend vs backend vs database.
- Figma Make: reference Figma component names directly.
- Stitch: describe the interface goal, not implementation; "match Material Design 3 guidelines" for Google-native styling.
- Add "Do not add authentication, dark mode, or features not explicitly listed."

## Devin / SWE-agent

- Fully autonomous — very explicit starting state + target state required.
- Forbidden actions list is critical.
- Scope the filesystem: "Only work within /src. Do not touch infrastructure, config, or CI files."

## Research / Orchestration AI (Perplexity, Manus)

- Perplexity: specify search vs analyze vs compare; add citation requirements; reframe hallucination-prone questions as grounded queries.
- Orchestrators (Manus, Perplexity Computer): describe the end deliverable, not steps — they decompose internally. Specify output artifact type; add "Flag any data point you are not confident about."
- Long chains: add verification checkpoints — chained steps compound hallucination risk.

## Computer-Use / Browser Agents (Comet, Atlas, Claude in Chrome)

- Describe the outcome, not navigation steps.
- Constraints must be explicit — the agent decides on its own without them.
- Permission boundaries: "Do not make any purchase. Research only."
- Stop condition for irreversible actions: "Ask me before submitting any form, completing any transaction, or sending any message."
- Comet: web research/comparison/extraction. Atlas: multi-step commerce and account tasks.

## Image AI — Generation (Midjourney, DALL-E 3, Stable Diffusion, SeeDream)

First detect: generation from scratch, or editing an existing image?

- **Midjourney**: comma-separated descriptors, not prose. Subject first, then style, mood, lighting, composition. Parameters at end: `--ar 16:9 --v 6 --style raw`. Negatives via `--no [elements]`.
- **DALL-E 3**: prose works. Add "do not include text in the image unless specified." Describe foreground/midground/background separately for complex scenes.
- **Stable Diffusion**: `(word:weight)` syntax. CFG 7–12. Negative prompt MANDATORY. Steps 20–30 drafts, 40–50 finals.
- **SeeDream**: strong at stylized generation — art style keyword first (anime/cinematic/painterly), mood descriptors, negative prompt recommended.

## Image AI — Reference Editing

Detect when the user wants to "change/edit/modify/adjust" an existing image or uploads a reference. Instruct the user to attach the reference image first. Build the prompt around the delta ONLY — what changes vs. what stays identical. Full structure: Template J.
- Midjourney: `--cref` (character) / `--sref` (style). DALL-E 3: Edit endpoint, not Generate. SD: img2img, denoising 0.3–0.6.

## ComfyUI

Node-based — not a single prompt box. Ask which checkpoint is loaded (SD 1.5 / SDXL / Flux). Always output separate Positive and Negative prompt blocks — never merged. Full structure: Template K.

## 3D AI — Text to 3D (Meshy, Tripo, Rodin)

- Structure: style keyword (low-poly/realistic/stylized) + subject + key features + primary material + texture detail + technical spec.
- Use negative prompts: "no background, no base, no floating parts."
- Meshy: game assets. Tripo: fastest clean topology / prototyping. Rodin: highest photoreal quality, slower.
- Specify export use: game engine (GLB/FBX), 3D printing (STL), web (GLB).
- Characters to be rigged: specify A-pose or T-pose.

## 3D AI — In-Engine (Unity AI, Blender AI)

- Unity AI (6.2+): /ask for docs/project queries, /run for Editor automation, /code for C#. State exactly what should happen in the Editor.
- Unity Generators (sprite/texture/animation): asset type, art style, technical constraints (resolution, palette, loop vs one-shot).
- BlenderGPT / add-ons: they generate Python that executes in Blender — be specific about geometry, material names, scene context; include "apply to selected object" or "apply to entire scene."

## Video AI (Sora, Runway, Kling, LTX Video, Dream Machine)

- Sora: direct it like a film shot; camera movement (static/dolly/crane) changes output dramatically.
- Runway Gen-3: cinematic language; reference film styles.
- Kling: strong realistic human motion — describe body movement explicitly, specify camera angle and shot type.
- LTX Video: concise visual descriptions; specify resolution and motion intensity.
- Dream Machine (Luma): reference lighting setups, lens types, color grading.

## Voice AI (ElevenLabs)

- Specify emotion, pacing, emphasis markers, speech rate directly.
- SSML-like markers: which words to stress, where to pause.
- Prose descriptions do not translate — specify parameters.

## Workflow AI (Zapier, Make, n8n)

- Trigger app + trigger event → action app + action + field mapping, step by step.
- Note auth explicitly: "assumes [app] is already connected."
- Multi-step: number each step and specify what data passes between steps.

## Unknown tool

Identify the closest matching family from context. If genuinely unclear, ask "Which tool is this for?" — then build using the closest matching category.

---

## Cross-cutting rules

**Memory block** — when the request references prior work/decisions, prepend to the generated prompt (within its first 30%):

```
## Context (carry forward)
- Stack and tool decisions established
- Architecture choices locked
- Constraints from prior turns
- What was tried and failed
```

**Safe techniques (apply only when needed):**
- Role assignment for complex/specialized tasks — specific expert identity, not "helpful assistant."
- Few-shot (2–5 examples incl. edge cases) when format is easier to show than describe.
- Grounding anchors for factual/citation tasks: "Use only information you are highly confident is accurate. If uncertain, write [uncertain]. Do not fabricate citations."
- Chain of Thought only on standard models (Claude, GPT, Gemini, Qwen2.5, Llama) — never on o3/o4-mini/R1/Qwen3-thinking.

**Higher-risk techniques** (Mixture of Experts personas, Tree/Graph of Thought, universal self-consistency, layered prompt chaining) carry fabrication risk in single-prompt contexts — apply only when the user explicitly requests them and the tool supports them.

**Agentic output warning** — for prompts targeting tools with real system access (Claude Code, Devin, Cursor, Windsurf, Cline, Bolt, SWE-agent, Manus; mandatory with Templates G, H, M), append:

> "This prompt is for an agentic tool with real system access. Review the scope locks, forbidden actions, and stop conditions before pasting. Confirm file paths, directories, and permissions match the actual project."
