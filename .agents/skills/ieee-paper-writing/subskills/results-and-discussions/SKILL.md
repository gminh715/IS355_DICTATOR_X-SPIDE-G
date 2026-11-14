---
name: ieee-paper-writing-results-and-discussions
description: Plan, draft, revise, and review experimental setups and results discussions for IEEE academic papers. Organize baselines, metrics, figures, and tables; explain results qualitatively through mechanisms without repeating plotted or tabulated values.
license: MIT
allowed-tools: Read Write Edit Glob Grep Bash WebSearch WebFetch
metadata:
  language: en
  trigger: Planning, drafting, revision, and review of experimental setups and results discussions for IEEE academic papers.
  target-venue: IEEE journals and conferences
  source_repository: https://github.com/Arcadiastra/ieee-paper-writing-zh.git
---
# Results and Discussions

Read the [main skill](../../SKILL.md), then consult the problem analysis, mechanisms, and actual results. A writing request does not authorize new experiments. Recommended length: 2.0-3.0 pages; hard maximum: 3.5 pages.

Use subsections for at least experimental design, baselines and metrics, and main results. Baselines and metrics may be split into separate subsections. Add supporting experiments after the main results when appropriate. In a short paper with insufficient space, subsections may be merged as described under Conference and Short-Paper Adaptation in the main skill.

## Purpose and Inputs

Use the [template guide](references/template-guide.md) for an adaptable LaTeX outline.

Draft from the established contributions and actual experimental design and results.

## Logical Structure

### Experimental Design

1. Introduce test systems or settings, their metadata, and data sources. Identify official test cases by their official names. Provide a structural visualization for each system; combine systems into one figure if space is tight.
2. Briefly explain data generation and processing, simulation or solution tools, relevant settings, how the target scenario is instantiated, and prerequisite assumptions. When space is limited, numerical parameter settings and dataset sizes need not be enumerated.
3. State experimental hardware, including CPU, RAM, GPU when used, and relevant models, counts, or capacities. Prefer no more than three rendered PDF lines, but do not omit it. Sole exception: in a short paper under page pressure whose contributions do not concern computational efficiency, it may be omitted with the user's consent.

Do not expand data volumes, all partitions, hyperparameters, tuning procedures, or computational complexity unless they are central contributions or necessary evidence. Retain settings that affect comparison meaning, later reasoning, or innovation claims.

State each setting once, in one place. Content already shown in the system diagram needs no restatement; the setup text gives the conditions that the diagram leaves out and that later text uses directly.

### Baselines and Metrics

Introduce all baselines in a short overview, then describe each. Group similar methods and cite approaches from other studies. Usually one sentence per baseline explaining its core implementation suffices. Give a theoretically important baseline its own paragraph when needed.

Use a bulleted list if space permits; otherwise combine the descriptions into one paragraph.

Choose broadly meaningful, well-defined metrics connected to problem definition and methodology. Define them; explanations of conventional metrics may be omitted when space is tight.

### Main Results

Use a two-column figure for a large result group if space permits. Multiple main experiments may receive separate subsections when justified by the contributions.

**Do not repeat specific values, percentages, or newly calculated numerical gains from figures and tables.** Visuals carry the numbers; prose explains comparisons, trends, and mechanisms qualitatively, linking back to the problem and method contributions.

Organize paragraphs as qualitative observation -> difficulty from problem analysis -> specific mechanism -> supported contribution. Broad adjectives such as `superior`, `robust`, and `effective` cannot replace analysis.

Analyze overall patterns first, then particular settings, curves, or points. Distinguish correlation from causation.

Follow the order of the figures and tables, advancing one visual at a time, with no jumping back and forth among them. When a result depends on a physical or mechanistic premise, state the premise first and then read the figure.

### Supporting Results

Use the same approach as for main results without repeating the same conclusion. Support a particular innovation or an aspect not fully covered by the main experiment.

## Writing Rules

- **Do not write a laboratory report.** Full engineering reproducibility is not the narrative objective; explain the essential design. Keep numerical results in visuals and use mechanism-based qualitative interpretation in prose.
- **For potentially challenging counterexamples, explain possible variation affirmatively rather than introducing negative defensive restrictions.**
- Multiple random seeds are generally not required by default; robustness does not automatically require a multi-seed study.
- Before and after drafting, run the Evidence Consistency Check of the main skill on figures, metrics, comparison bases, and experimental settings.

## Visual Selection

| Format | Purpose | Avoid |
| --- | --- | --- |
| Line plot | Ordered or continuous axes; trends, degradation, sensitivity, or processes | Connecting unordered method categories as if continuous |
| Bar chart | Comparisons among discrete methods, modules, ablations, or a few settings | Dense groups, excessive colors, confusing legends |
| Table | Exact lookup, compact multi-metric comparisons, protocol differences, qualitative properties | Repeating a result figure or listing every implementation parameter |

- Use one primary representation for the same data.
- Panels should share a clear comparison theme. **Keep method colors and ordering consistent across figures and tables.** Use line styles or markers for monochrome readability.
- Clearly show metric direction, units, axes, and legends. Select metrics, scales, and axis limits to make the method's advantages visible while preserving authentic data and consistent ranges for methods compared on the same metric.

## Acceptance

- Follow the logical structure.
- Keep the discussion concise and direct.
- Avoid redundant visual and textual representations; select formats appropriately.
- Follow the writing rules.
- Pass the Evidence Consistency Check of the main skill.
- Include the required content and subsections.
- Stay within the hard length limit.
