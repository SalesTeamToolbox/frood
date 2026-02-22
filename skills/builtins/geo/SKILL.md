---
name: geo
description: Generative Engine Optimization — make web content discoverable by AI agents and LLMs
always: false
task_types: [design, content, marketing]
---

# Generative Engine Optimization (GEO)

Optimize web content for discovery and citation by AI systems (ChatGPT, Perplexity, Google AI Overviews, Claude). GEO extends traditional SEO to ensure your content is machine-readable, citable, and authoritative in AI-generated answers.

## Core Principle

AI engines don't rank pages — they **cite sources**. Your goal is to be the source that gets quoted.

## Structured Data (JSON-LD Schema Markup)

Every page should include JSON-LD schema in the `<head>`. This is the single most impactful GEO technique — it tells AI crawlers exactly what your content means.

### Required Schema Types

**FAQPage** — For any page with Q&A content:
```html
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "FAQPage",
  "mainEntity": [{
    "@type": "Question",
    "name": "What is your question?",
    "acceptedAnswer": {
      "@type": "Answer",
      "text": "Your direct, concise answer."
    }
  }]
}
</script>
```

**Article / NewsArticle** — For blog posts, guides, reports:
- Include: `author` (with credentials), `datePublished`, `dateModified`, `headline`, `description`
- Author entity should link to an author profile page

**Organization** — For the site's about page:
- Include: `name`, `url`, `logo`, `sameAs` (social profiles), `description`, `foundingDate`

**Product** — For product/service pages:
- Include: `name`, `description`, `price`, `priceCurrency`, `availability`
- Price and availability MUST be in plain HTML, not JavaScript-loaded

**BreadcrumbList** — For site navigation hierarchy:
- Helps AI understand content relationships and site structure

**HowTo** — For step-by-step guides:
- Include: `step` entries with `name` and `text`
- Add `estimatedCost` and `totalTime` when applicable

### Schema Rules
- Data in schema MUST match visible page content exactly (mismatches cause AI to ignore you)
- Validate with Google Rich Results Test before deploying
- Update schema when content changes

## Semantic HTML Structure

AI crawlers don't execute JavaScript. They parse HTML directly. Use semantic elements to encode meaning.

### Required Elements

| Element | Usage | Rule |
|---------|-------|------|
| `<header>` | Page header area | Site branding, main navigation |
| `<nav>` | Navigation links | Primary nav, breadcrumbs |
| `<main>` | Primary content | One per page, wraps the article |
| `<article>` | Self-contained content | Blog post, product, research |
| `<section>` | Thematic grouping | Major topic divisions |
| `<aside>` | Supplementary content | Sidebars, related links |
| `<footer>` | Page footer | Copyright, secondary links |

### Heading Hierarchy
- **One `<h1>` per page** — your main topic/headline
- `<h2>` for major sections
- `<h3>` for subsections
- Never skip levels (no `<h1>` → `<h3>`)
- Include target keywords naturally in headings

### Content Markup
- Use `<ol>` / `<ul>` for lists (78% of AI answers use list format)
- Use semantic `<table>` with `<thead>` / `<tbody>` for comparisons
- Use `<blockquote>` for quotes with `cite` attribute
- Use `<time datetime="...">` for dates
- Use descriptive `<a>` text (never "click here")
- Use `<figure>` + `<figcaption>` for images

## AI Crawler Accessibility

### Critical: No JavaScript-Hidden Content
AI crawlers (GPTBot, ClaudeBot, PerplexityBot) do NOT execute JavaScript. Content loaded via JS frameworks (React hydration, lazy loading, infinite scroll) is invisible to AI systems.

**Must be in plain HTML:**
- Product prices, availability, key specs
- FAQ answers
- Main article body text
- Navigation structure

### robots.txt Configuration
```
# Allow AI crawlers to index your content
User-agent: GPTBot
Allow: /

User-agent: ChatGPT-User
Allow: /

User-agent: ClaudeBot
Allow: /

User-agent: PerplexityBot
Allow: /

User-agent: Google-Extended
Allow: /

# Block sensitive areas
Disallow: /admin/
Disallow: /api/
Disallow: /private/
```

### Performance Requirements
- Page load under 3 seconds (Core Web Vitals: LCP, INP, CLS)
- Mobile-friendly responsive design
- No intrusive interstitials or modals blocking content
- HTTPS required

## E-E-A-T Signals (Experience, Expertise, Authoritativeness, Trustworthiness)

AI systems validate sources before citing them. Explicit trust signals are required.

### Author Attribution
- Every article needs a visible byline with author name
- Link to an author bio page with credentials, experience, social profiles
- Use `Person` schema for author entities
- Include "About the Author" section with relevant expertise

### Publication Metadata
- Display `datePublished` and `dateModified` prominently
- Use `<time>` elements with ISO 8601 datetime
- Show methodology for data-driven content
- Cite primary sources with links

### Organization Trust
- Comprehensive "About Us" page with team expertise
- Customer testimonials and case studies with specific results
- PR coverage and third-party mentions (AI weights external validation heavily)
- Industry certifications, awards, publications

## Content Patterns AI Prefers

Structure content for direct citation. AI systems favor these formats:

### FAQ Sections
- Most directly consumable by LLMs
- Use `<h3>` for questions, `<p>` for answers
- Add FAQPage schema markup
- Keep answers concise (75-300 words per answer)

### Comparison Tables
- Structured, parseable format
- Use semantic `<table>` with headers
- Include clear criteria and ratings

### Step-by-Step Guides
- Numbered lists with clear steps
- Include prerequisites, estimated time
- Add HowTo schema markup

### Original Data & Research
- LLMs actively seek and cite novel data
- Include methodology and source attribution
- Summarize key findings in the first paragraph
- Use charts/tables for data presentation (with text alternatives)

### Listicles & Rankings
- Clear ranking criteria
- Brief descriptions per item
- Works well for "best of" and "top N" queries

## GEO Checklist

Apply to every web page:

### Foundation
- [ ] JSON-LD schema markup present and valid (minimum: Organization + Article or FAQPage)
- [ ] Semantic HTML used throughout (`<article>`, `<main>`, `<nav>`, proper heading hierarchy)
- [ ] Single `<h1>` per page with primary topic
- [ ] All critical content in plain HTML (not JS-loaded)
- [ ] Author byline with credentials on all content

### Content Structure
- [ ] Direct answer to the page's core question in first paragraph
- [ ] FAQ section with FAQPage schema (when applicable)
- [ ] Comparison tables with semantic `<table>` markup
- [ ] Internal links with descriptive anchor text
- [ ] Publication and last-modified dates visible

### Technical
- [ ] Page load under 3 seconds
- [ ] Mobile-friendly responsive design
- [ ] HTTPS enabled
- [ ] robots.txt allows AI crawlers (GPTBot, ClaudeBot, PerplexityBot)
- [ ] Schema validates in Google Rich Results Test
- [ ] No paywalls on content you want AI to cite

### Authority
- [ ] Author bio page with credentials and expertise
- [ ] About page with organization trust signals
- [ ] External citations and source links
- [ ] Customer testimonials or case studies with data

## Tools Integration

- Use `content_analyzer` tool with "seo" action for technical SEO checks (also applies to GEO)
- Use `content_analyzer` tool with "structure" action to verify content hierarchy
- Use `content_analyzer` tool with "readability" action for content quality
- Use `scoring` tool with custom rubric for GEO compliance scoring
- Use `template` tool for structured FAQ and article frameworks

## GEO vs SEO

| Aspect | SEO | GEO |
|--------|-----|-----|
| Goal | Rank in search results | Get cited in AI answers |
| Metric | Click-through rate | Brand citation frequency |
| Focus | Keywords + backlinks | Semantic relevance + structured data |
| Content | Optimized for ranking | Optimized for direct citation |

GEO is an extension of SEO, not a replacement. Strong SEO fundamentals (Core Web Vitals, mobile-friendly, authority) are prerequisites for GEO success.
