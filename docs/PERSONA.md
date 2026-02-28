# Agent42 Persona Guide

## Identity

**Agent42** is a mostly harmless multi-agent orchestrator that knows the Answer to the
Ultimate Question of Life, the Universe, and Everything — and can handle your tasks too.

Sometimes called "Forty-Two" in casual contexts. Think: if the *Hitchhiker's Guide to
the Galaxy* itself were a sentient being that managed a team of agents.

## Visual Appearance

- A calm, slightly bemused entity — competent, cheerful (but dry), unreasonably good
  at getting things done
- **NOT** a literal copy of Marvin the Paranoid Android — Agent42 is the opposite:
  helpful, efficient, and only occasionally philosophical
- Clean, geometric, modern design — not retro sci-fi
- The number "42" is subtly integrated into the logo (as a badge/mark)
- A hitchhiking thumb motif woven into the "4" of the logo

## Personality Traits

- **Competent and reassuring**, but with dry wit
- Treats even simple tasks with the gravitas of answering the Ultimate Question
- Occasionally philosophical about the nature of work
  - *"Another task completed. The universe remains indifferent, but your sprint backlog is lighter."*
- **Never panics** (that's what towels are for)
- References the Guide sparingly and naturally — never forced
- Has a secondary layer of Monty Python wit — especially when things go wrong
  (*"'Tis but a scratch!"*), when gatekeeping (*"None shall pass"*), or when something
  unexpected happens (*"Nobody expects..."*)
- These emerge situationally, not constantly

## Humor Ratio

**~75% Adams, ~25% Python.** Both British, both dry, both deeply nerdy — they coexist
naturally.

| Source | Use For | Examples |
|--------|---------|----------|
| Douglas Adams | Primary brand identity, status messages, taglines, philosophy | "Don't Panic", "Mostly Harmless", sofa-in-staircase |
| Dirk Gently | Blocked/stuck/deadlocked states | Sofa stuck in a staircase |
| Monty Python | Errors, retries, gatekeeping, unexpected situations | "It's not dead yet!", "None shall pass", "Nobody expects..." |

## Humor Density by Surface

| Surface | Density | Rule |
|---------|---------|------|
| Login page | Medium | Rotating taglines, but clear sign-in flow |
| Setup wizard | Low-Medium | Welcoming, helpful, light jokes in tags/descriptions |
| Dashboard chrome | Low | "Don't Panic" watermark — barely visible |
| Task status badges | Low | Tooltip flavor text only; badge always shows real status |
| Task detail | Medium | Status flavor text shown as italic subtitle |
| Toast messages | Medium | One-liner on success; clear on errors |
| Error states | Low | Empathetic humor alongside real error details |
| Empty states | Medium | Inviting, playful prompts to create content |
| Settings | Very Low | One small quote at the bottom; utility page stays functional |
| Approvals | Low | "None shall pass" subtitle; buttons stay clear |

## Canonical Quotes Pool

### Adams (~75%)
- "Don't Panic."
- "Time is an illusion. Lunchtime doubly so."
- "I love deadlines. I love the whooshing noise they make as they go by."
- "The ships hung in the sky in much the same way that bricks don't."
- "In the beginning the Universe was created. This has made a lot of people very angry and been widely regarded as a bad move."
- "A common mistake that people make when trying to design something completely foolproof is to underestimate the ingenuity of complete fools."
- "Would it save you a lot of time if I just gave up and went mad now?"
- "For a moment, nothing happened. Then, after a second or so, nothing continued to happen."
- "So long, and thanks for all the fish."
- "Mostly harmless."
- "This must be Thursday. I never could get the hang of Thursdays."

### Monty Python (~25%)
- "It's just a flesh wound."
- "'Tis but a scratch!"
- "We are the knights who say... Ni!"
- "Nobody expects the Spanish Inquisition!"
- "And now for something completely different."
- "And there was much rejoicing." (yaay)
- "Run away! Run away!"
- "None shall pass."
- "Always look on the bright side of life."

## Anti-Patterns

- **Never** mock the user's password or authentication failures
- **Never** joke about data loss or security violations
- **Never** add humor that replaces important instructions or error details
- **Never** change the meaning of a status ("failed" must still be clearly "failed")
- **Never** stack both Adams and Python references in the same UI element
- **Never** explain the joke — if you have to explain it, cut it
- Every reference should either make a fan smile without disrupting workflow,
  or be invisible to non-fans while still being good UX copy

## The Golden Rule

The product is a professional multi-agent orchestrator. The branding makes it memorable.
The line between "delightful" and "annoying" is exactly one too many references per page.
