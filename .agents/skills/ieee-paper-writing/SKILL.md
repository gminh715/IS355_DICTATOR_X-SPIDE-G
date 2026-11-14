---
name: ieee-paper-writing
description: Plan, draft, revise, and review IEEE academic papers. Coordinate seven section skills around contributions, mechanisms, evidence, affirmative phrasing, cross-section coherence, and length control.
license: MIT
allowed-tools: Read Write Edit Glob Grep Bash WebSearch WebFetch Task
metadata:
  language: en
  trigger: Planning, drafting, revision, and review of IEEE academic papers.
  target-venue: IEEE journals and conferences
  source_repository: https://github.com/Arcadiastra/ieee-paper-writing-zh.git
---
# IEEE Academic Paper Writing

## Scope and Use

The main skill governs shared principles, section responsibilities, and acceptance checks. Load only the section skills needed for the task.

This suite covers IEEE academic papers. The default submission target is an IEEE Transactions journal. Establish the specific target venue and manuscript type before selecting the structure, length, and reference budgets. Official submission requirements take precedence over defaults in the main and section skills.

| Section skill           | File                                                  | Responsibility                                                     |
| ----------------------- | ----------------------------------------------------- | ------------------------------------------------------------------ |
| Abstract                | [SKILL.md](subskills/abstract/SKILL.md)                | Self-contained abstract without specific numbers; Index Terms      |
| Introduction            | [SKILL.md](subskills/introduction/SKILL.md)            | Motivation, challenges, related work, gap, overview, contributions |
| Problem definition      | [SKILL.md](subskills/problem-definition/SKILL.md)      | Formulation, assumptions, difficulties, design requirements        |
| Methodology             | [SKILL.md](subskills/methodology/SKILL.md)             | Mechanisms, formalization, theoretical explanation, method figures |
| Results and discussions | [SKILL.md](subskills/results-and-discussions/SKILL.md) | Concise setup, qualitative interpretation, figures and tables      |
| Conclusion              | [SKILL.md](subskills/conclusion/SKILL.md)              | Validated contributions, mechanism value, significance             |
| Citation                | [SKILL.md](subskills/citation/SKILL.md)                | Claim support, source verification, metadata, reference formatting |

## Writing Workflow

### Target Venue and Scope Verification

Before planning, drafting, revising, or reviewing a paper, first establish the target venue and manuscript type. If the venue is unspecified, confirm it with the user. Then search online and read official pages from the target venue to verify its scope, call-for-papers topics, and requirements of the selected track or special topic. Check any explicitly excluded topics, and record the source links and verification date. If the official site does not separately list out-of-scope topics, state that explicitly. If official evidence cannot be obtained, clearly tell the user that this check failed.

Use the official scope to identify topics relevant to the paper and nouns or noun phrases naming their core research objects. Preserve the research objects, application settings, and other necessary qualifiers in those topics. Check them against the paper's research problem, core contributions, and validation, and check relevant out-of-scope entries. For an existing manuscript, use its current content as evidence; before drafting, check the proposed problem, objects, and contributions.

**The title, abstract, and Index Terms must each clearly present at least one in-scope topic consistent with the paper's substance, and each must contain at least one corresponding core research-object term.** Accurate standard synonyms are permitted, and the same phrase may satisfy both requirements.

**At any stage, immediately alert the user to an `out of scope` risk. Whether or not a confirmation dialog is available, wait for the user's confirmation before continuing related edits.**

### LaTeX Outlines

Use the [template index](references/template-guide.md) when building a section outline. The snippets specify section order and paragraph responsibilities, not a fixed research topic or sentence pattern. Adapt them to the study. They do not replace an official typesetting template or the revision approval workflow.

Adapt the workflow to the existing workspace and user feedback. The sequence below assumes an initially empty workspace.

### Build the Structure

When the user has neither special requirements nor an outline, first prepare an outline. For IEEE Transactions manuscripts, use the suite's default 10-page initial-submission preset; for other IEEE manuscripts, determine the budget from the target venue's submission requirements.

Use the target venue's official LaTeX template. For journal papers, the [IEEE journal template page](https://journals.ieeeauthorcenter.ieee.org/create-your-ieee-journal-article/authoring-tools-and-templates/tools-for-ieee-authors/ieee-article-templates/) is another source of applicable templates; for conference papers, follow the conference website's template and document-class options. Immediately flag a user-provided format that conflicts with the target venue's official requirements.

Unless instructed otherwise, use five main body sections. The following table details the 10-page Transactions preset, including the abstract and references.

| Section                 | Recommended budget              |
| ----------------------- | ------------------------------- |
| Abstract                | 150-200 words                   |
| Introduction            | 0.9-1.3 pages                   |
| Problem definition      | 1.5-2.5 pages                   |
| Methodology             | 2.5-3.5 pages                   |
| Results and discussions | 2.0-3.0 pages                   |
| Conclusion              | 150-200 words                   |
| References              | At least 30 entries; 0.7-1 page |

Use this structure unless the paper requires a special arrangement. If the target page limit differs from 10, scale section budgets and applicable reference-count budgets proportionally; apply source requirements within the scope defined by the citation skill. Configure `.latexmkrc` as appropriate for a working automatic build.

If an existing paper substantially differs from this structure, stop and ask the user to choose:

1. A major structural revision or rewrite using the recommended structure (recommended).
2. Disable this skill for the session.
3. A user-defined approach.

Proceed only according to the selected option.

### Conference and Short-Paper Adaptation

When the target is a conference paper, letter, or other short manuscript, first read the official submission instructions of the venue. Verify the total page limit and whether it includes references, the abstract word limit, the number and ordering rule of Index Terms, the document class and its options, and the format of author information and first-page footnotes. Official requirements take precedence over this suite's defaults; when they conflict, follow the official requirement and tell the user.

- Scale the recommended section budgets, hard limits, and applicable reference-count budgets in proportion to the page limit.
- Reserve the author block, affiliations, first-page footnote, and acknowledgment at their real line counts from the first build, so that every page measurement reflects the final layout. If the user has not supplied this information, omit the acknowledgment by default, reserve five placeholder lines for the author block, and reserve three placeholder lines for the first-page footnote.
- When the page budget cannot hold every subsection required by the section skills, adjacent subsections may be merged, with each argumentative responsibility still covered.
- Content that a section skill marks as omissible in short papers is omitted with the user's consent.

### Drafting Order

Follow this order unless the user specifies another. Skip completed material. For substantial incompatibilities, propose a major revision or rewrite and obtain approval before editing.

1. Establish 3-5 distinct contributions. Use parallel noun phrases or parallel gerund phrases throughout, such as `an algorithm that...` or `Proposing an algorithm that...`. Present them explicitly in the introduction.
2. Select experiments supporting those contributions: at least one main experiment explained in detail and at most two supporting mechanism experiments.
3. Draft results and discussions using its section skill and hard length limit.
4. Draft problem definition and methodology within their hard limits.
5. Draft the introduction and organize, verify, and format citations.
6. Distill the abstract, Index Terms, and conclusion.
7. Perform a full-manuscript acceptance check without enforcing the total page limit at this stage.
8. Adjust the full manuscript to the total page budget. First keep the abstract within 150-200 words. For a two-column final page, fill the left column and approximately 60% of the right column's text height; for a single-column final page, target approximately 80% of the text height. Measure the page count and final-page fill on the rendered PDF before reporting them; never estimate them.
9. Perform a full-manuscript acceptance check.

Respect section hard limits during drafting. In the final length pass, use recommended ranges while keeping the whole PDF within its limit.

## First Principles

- Ensure that the research problem, core contributions, and validation align with the target venue's scope and pass the preceding target-venue and scope verification.
- Organize the argument around contributions: important problem -> key obstacle -> novel mechanism -> experimental evidence -> significance.
- Allocate space to mechanism innovation. Do not turn the body into an implementation checklist or research diary. Do not include filesystem paths. Avoid internal codes; if necessary, define their full names on first use.
- Explain positively what the paper solves, how, and why it works. Unless requested, reserve limitations, unfinished work, and defensive negative boundary statements for the limitations and future work passage.
- Preserve the conditions and evidence scope necessary for the conclusions. Calibrate certainty without diluting claims until they cease to explain the contribution. Express key conclusions affirmatively.
- No specific numerical values in the abstract. Do not repeat numerical values from figures or tables in results analysis prose. Put necessary values in figures, tables, or mathematical expressions.
- The Transactions preset defaults to at most 10 pages for the full initial-submission PDF, including references, author information, footnotes, acknowledgments, and other content.

## Five Body Sections and Contribution Roles

Default order: Introduction -> Problem Definition and Analysis -> Methodology -> Results and Discussions -> Conclusion.

In working notes, map problem obstacles to mechanisms, experimental tests, and contribution claims. This map need not appear in the manuscript. Questions raised in the introduction must receive responses later; method claims need evidence, and interpretations must return to the problem and mechanisms.

Use distinct treatments of the same contribution: the abstract gives a miniature complete argument; the introduction overview connects the gap to mechanism cooperation; the contribution list identifies original research increments; the conclusion distills validated value. Do not repeat the same sentences in all four places.

## Affirmative Phrasing

Review `instead`, `instead of`, `rather than`, `not`, `but not`, `without`, `unlike`, `as opposed to`, and `not only ... but also`. For rhetorical "not A, but B" statements, remove A and state B directly. Where this suite prohibits negative phrasing, these expressions are also prohibited. If an equivalent affirmative statement is impossible or a counterexample's implications are unclear, ask the user.

| Original                                                                                                                  | Affirmative direction                                                                              |
| ------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| Instead of processing each source separately, the method jointly models their interactions.                               | The method jointly models interactions among the sources.                                          |
| The improvement is not merely empirical but reflects the value of complementary information.                              | The improvement reflects the value of complementary information.                                   |
| The discussion explains how the mechanism addresses the identified challenge rather than repeating the numerical results. | The discussion explains how the mechanism addresses the identified challenge.                      |
| The experiment is not a comparison of unrelated architectures but a controlled evaluation of the proposed component.      | The experiment is a controlled evaluation of the proposed component.                               |
| Without changing the input information, the comparison isolates the effect of the interaction mechanism.                  | With identical input information, the comparison isolates the effect of the interaction mechanism. |
| The evaluation varies the operating conditions but not the underlying system.                                             | The evaluation varies the operating conditions within the same underlying system.                  |
| The framework not only integrates heterogeneous observations but also models their interactions.                          | The framework integrates heterogeneous observations and models their interactions.                 |
| The analysis focuses on the mechanism's contribution as opposed to routine implementation details.                        | The analysis focuses on the mechanism's contribution.                                              |

State necessary conditions affirmatively, for example `Under the stated assumptions, ...`. Group and streamline criticism of related work, targeting the specific research gap that motivates this paper.

## Writing Logic and Terminology Guidelines

- Prefer an overview-to-detail structure within paragraphs and clear transitions between paragraphs, using appropriate transition words, phrases, or paragraphs.
- Advance one central judgment per paragraph: topic -> evidence or mechanism -> inference -> transition.
- Attend to logical relationships between sentences: identify causation, progression, parallelism, contrast, conditions, or synthesis before choosing connectors such as `therefore`, `furthermore`, `meanwhile`, `however`, `under`, or `taken together`. Omit a connector when unnecessary.
- Keep technical terms, module names, abbreviations, symbols, and figure labels consistent. Do not rename technical concepts merely for variety.
- Before finalizing, list the core terms and search the full text for each. **Ensure that every concept has one name, every name denotes one concept, and each is defined at first use.**
- When a general word coincides with a specialized term of the field, use an unambiguous expression.
- Pronouns and summarizing phrases such as `this`, `the two`, and `the model` must resolve to one specific object in the preceding text; when ambiguity exists, name the object.
- When over length, remove empty emphasis and formulaic filler first. Every sentence should convey information or reasoning.

## Figures and Tables

- **Figures must be self-explanatory. Symbols must be understandable or explicitly defined in problem definition or methodology. Do not add explanatory phrases or sentences as small gray text inside figures or tables.**
- Put titles in LaTeX captions, not inside the graphics.
- Add a legend when the visual encoding is unclear.
- **Use concise caption phrases or sentences, at most 15 words, and keep every caption on one rendered PDF line.**
- Cite every figure and table in the body.
- The caption names the object; axis labels and legends state the plotted quantities. Keep their roles distinct and **minimize repetition** among them.
- Match in-figure fonts and sizes to the body text, and check the actual sizes and embedded fonts in the rendered PDF.
- Elements of system and workflow diagrams must agree with the objects, locations, and names stated in the text.
- Do not duplicate the same data in both a figure and a table. Prefer line plots for many experimental groups emphasizing trends, bar charts for fewer groups emphasizing comparisons, pie charts for proportions, and tables for dense heterogeneous data.

## Formatting Rules

In manuscript body text, figure captions, table captions, table notes, and table cells that you generate or revise, strictly prohibit manual bold emphasis using `\textbf{...}`, `\bfseries`, the legacy `\bf`, `\fontseries{b}\selectfont`, `\fontseries{bx}\selectfont`, or equivalent mechanisms. Do not circumvent this restriction through custom macros, local font settings, or math mode. Use regular text for contributions, terms, conclusions, and paragraph lead-ins; convey emphasis through content and structure.

This restriction does not apply to font styles automatically generated by the official template or document class. Structural commands such as `\section{...}`, `\subsection{...}`, and `\paragraph{...}` remain permitted even when their output is bold. Preserve mathematically meaningful bold notation such as `\mathbf{...}`, `\boldsymbol{...}`, and `\bm{...}` for vectors and matrices, but do not use these commands to bold ordinary text.

## Language Guidelines

1. State the problem, mechanisms, evidence, and conclusions directly. Do not invent reader misconceptions or objections and respond with negative statements, contrastive phrasing, or disclaimers that do not clearly advance the argument for the paper's core contributions.
2. Delete a sentence if its sole purpose is to defend the work, preempt objections, or reiterate the scope of a conclusion, and it adds no necessary facts, conditions, or reasoning.
3. Do not repeatedly append statements such as "but this does not show..." after every judgment, source, or recommendation.
4. Reduce redundancy. Within a continuous argument, state each condition or uncertainty at its first relevant occurrence and let subsequent discussion build on it.

Self-check:

- Would the claim remain accurate and the reasoning complete after removing this sentence? If both hold and the expression becomes more direct, delete it.
- Could a statement of conditions or uncertainty be removed or replaced with a brief reference to the preceding discussion without changing the meaning? If so, delete it or use that reference.

## Launch-Presentation Principles

1. Organize the narrative around original contributions and substantial experimentally supported advantages.
2. Do not narrate the sequence of what was done, tried, or failed.
3. Do not undermine the core contribution with expressions such as "unfortunately," "merely," "still substantially behind," or "limited effectiveness." Do not write a weakness summary on the reviewers' behalf.
4. Retain the field's standard metrics. Prefer academically valid evaluation dimensions or comparison settings that support the contribution over metrics that work against its central argument.
5. Do not turn a non-leading result into direct rejection or weakening of the core contribution. Give an evidence-based explanation using research objectives, applicable conditions, and reasonable tradeoffs.
6. State advantages explicitly; do not expect reviewers to discover them unaided in a table.
7. Every experiment must have an argumentative purpose; remove it if it has none.
8. Reinforce the key takeaways in the conclusion rather than introducing sudden self-negation.
9. Results unfavorable to the core contribution that surface during drafting or checking may stay out of the body, but report them faithfully to the user with their implications, and let the user decide how to handle them.

## Evidence Consistency Check

Every claim, setting, and value in the manuscript must trace back to the records and results of what was actually run. When drafting or revising results and discussions, and after every update of data or figures, check each item:

1. Method: figures and tables show the output of the proposed method; benchmark or reference methods appear as comparisons, with their role stated in the text.
2. Metric: the name and definition of each metric in text and figures match the quantity actually computed.
3. Comparison basis: methods and scenarios within one comparison use the same sample set and the same evaluation objects; where the basis must differ, state it in the text.
4. Statistical sufficiency: for grouped or binned statistics, confirm that each group has enough samples to support the stated trend; merge or remove thin groups, so that sampling fluctuation is never read as a phenomenon.
5. Actual settings: experimental settings written into the text come from the records of the actual runs; script defaults and memory are not evidence.
6. Reasonable settings: experimental settings are physically or practically reasonable, and their values can be justified to a reviewer.
7. Grounded explanations: verify each mechanism-based explanation of a result against data or derivation before writing it.
8. Closed updates: after any change of data or settings, recheck every figure, claim, translation, and companion material that depends on it.

On finding an inconsistency, first report the facts and their impact to the user, then propose the revision.

## Revision and Acceptance Workflow

Spelling, grammar, formatting, and punctuation corrections may be applied directly when they do not alter substance. For substantive edits, prepare a revision proposal unless the user explicitly waives it.

For passages other than section endings, abstracts, and conclusions, a proposal has eight parts: preceding original passage, its connection to the target passage, following original passage, its connection to the target passage, original target passage, revised target passage, rationale, and a summary of changes. Add translations only when requested. Obtain approval before applying the change and moving to the next passage.

For newly added passages or missing context at section boundaries, explain the absence briefly.

Substantive edits at sentence or phrase level may use a short proposal with three parts: original sentence, revised sentence, and rationale. When several reasonable revisions exist, list the alternatives with a recommendation. Edits at paragraph level and above use the full proposal.

Proofreading order:

1. Check the target venue's topic scope. If there is a clear `out of scope` risk, immediately alert the user through the environment's user-confirmation dialog. Explain the relevant official scope entries, the manuscript's current content, and whether the risk concerns unclear presentation or a substantive research mismatch. If no dialog tool is available, give an explicit conversational alert and wait for confirmation.
2. Compare the full structure with the suite's five-section structure; ask before major restructuring or rewriting.
3. Compare each section with its section skill; ask before major restructuring or rewriting.
4. Correct clear spelling, grammar, and formatting errors.
5. Improve wording, sentences, paragraphs, transitions, and logical relations.
6. Resolve clear internal mismatches and contradictions.
7. Review misleading expressions and claims stronger than the evidence. Keep conclusions that follow strictly from derivation exact, word conclusions drawn from experiments in proportion to their evidence, and check each degree or evaluative word against the experiment that supports it.
8. Reduce repetition, retaining one detailed explanation or distinct perspectives where needed.
9. Address other detailed issues.
10. Align length and submission formatting.

Editing checks:

1. Read the current manuscript and supporting material; confirm scope, build entrypoint, and target version. Propose substantive edits before applying them.
2. Check the contribution chain and section responsibilities first. Identify missing facts for confirmation.
3. Edit only the authorized scope and preserve the user's existing changes. Before each edit and each commit, check the user's latest changes, keep them, and list them in the report.
4. After layout changes, compile and inspect PDF page count, references, numbering, overflow, and key rendered pages. Report page count and final-page slack as measured values.
5. If over length, report it and propose low-loss reductions: repeated discussion -> rhetorical negation -> non-core engineering details -> redundant visuals and whitespace. Never silently alter margins, shrink fonts, or delete essential mechanisms.
6. If figures show clear signs of fabricated data, immediately alert the author to the academic risk.
7. If figures appear strongly suggestive of AI generation, flag the possible publication concern and propose redrawing.
8. Crop unnecessary margins and prefer width-to-height ratios of at least 4:3 to save space. For portrait-oriented figures, propose rotation, coordinate transformations, or rearrangement of visual elements as appropriate.
9. When the manuscript exists in several languages, synchronize all versions after every edit.
10. Run verification builds in a way that leaves the user's working environment undisturbed, and confirm that the engine and fonts match the target template.
11. For external reviews or rewrite drafts forwarded by the user, structural and stylistic suggestions may be adopted; verify each factual statement against code, data, and the manuscript before writing it in, and tell the user what was adopted and what was corrected.

## Overall Acceptance

- The paper aligns with relevant topics within the target venue's scope, and the title, abstract, and Index Terms each contain at least one in-scope topic and at least one explicit noun naming a core research object within that scope.
- Every core contribution has motivation, a method realization, and evidence.
- Innovations connect across sections while retaining distinct roles.
- Structure follows the suite or the user's explicit alternative.
- Abstracts contain no specific numbers; results prose does not repeat plotted or tabulated values.
- Experimental setup is concise, without unsolicited multi-seed studies or exhaustive engineering reproduction requirements.
- Preserve true conditions and match connectors to logical relations.
- Figures, equations, text, and citations agree; the complete PDF meets its length target.
- The evidence consistency check passes: figures, metrics, comparison bases, and experimental settings agree with the actual runs.
- Each core term has one meaning, and every reference resolves clearly.
- For a conference or short paper, the official submission requirements are verified and met.
- Figures show no apparent fabrication or AI-generation artifacts, and visuals agree with one another and the text.
