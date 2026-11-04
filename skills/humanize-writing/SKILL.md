---
name: humanize-writing
description: Rewrite AI-sounding text, or draft new text, so it reads human-written. For resumes, cover letters, SOPs, 자소서, scholarship/job applications, emails and posts (Korean or English). Not for paper prose.
---

# Humanize writing (general)

Use for resume and CV bullets, cover letters, personal and research statements for jobs or scholarships, Korean 자기소개서 and 지원서, emails, and posts. For ML paper prose (abstract, intro, method, rebuttal), use `humanize-paper` instead.

Two modes:
- Rewrite: the user pastes text drafted by an AI (or asks "AI 같아?"). Diagnose, then rewrite.
- Draft: the user asks for new text. Apply every rule below while drafting, then run the check pass before returning anything.

The goal is text that a careful human reader accepts as written by the applicant. Edit for that reader, not for an AI detector. Never invent facts.

## Why AI text reads as AI

Two separate habits produce the patterns below, and they need opposite fixes.

1. The default choice. A model picks the option that fits the widest range of readers. So sentences signal importance instead of adding a fact, rhythm and formatting follow a rule, and ordinary facts get dressed up as pivotal. Fix: cut, and replace with the specific claim.
2. Compression. Drafts make inanimate things the subject of verbs that need a person, stack nouns, coin rare word pairs, turn nouns into ad hoc verbs, and drop optional words such as "that". Each of these slows a human reader. People keep or drop optional words by context; a compressed draft drops them almost always. Fix: unpack. Put the person back as the subject, spell out relations, keep the optional word when the next clause is long or surprising.

Cutting alone can make the second problem worse. Check both.

## Workflow

1. Reader and point. Name the reader (hiring manager at X, scholarship committee, a professor) and the one thing they should take away. Note the register and language.
2. Mark the patterns, strongest first (lists below). Check paragraph shape too: a contrast split over two sentences, three parallel examples, or the same closer after every paragraph is the same pattern at a larger scale.
3. Rewrite. Keep every supported claim. You may merge, split, and reorder. Do not add a fact, number, name, date, or outcome that is not in the source or the conversation. If a sentence needs a missing detail (a number, a project name, what actually changed), write a simpler true sentence and list the gap as a question at the end.
4. Check pass. Reread as the reader. Search again for the patterns that survive rewrites most often: not-X-but-Y, one-line closers, triads, dashes, bold labels, and in Korean the interpunct (·). Compare fact by fact against the source: nothing added, nothing dropped unless a pattern called for cutting it.
5. Return (format below).

## What to return

- Rewrite mode: the final text first. Then 2 to 5 short lines in the user's language naming the main changes. Then any missing-detail questions. Do not show an intermediate draft unless asked.
- "AI 같아?" questions: give a verdict, quote the specific sentences that read as AI and say why, then offer or give the rewrite.
- Draft mode: the final text, then the gaps you could not fill without inventing.

## Remove on one sighting

1. Not X but Y. "It's not just a project, it's a mission." "단순히 X가 아니라 Y입니다." Includes the split form ("This doesn't mean X. It means Y."), "X rather than Y", and a clipped tail ("..., no shortcuts"). Keep a contrast only when the reader actually believes X.
2. One-line closers and fragment rows. A last sentence that restates the paragraph: "That's what drives me." "그것이 제가 이 길을 택한 이유입니다." A sentence after an example that names its lesson. "No shortcuts. No excuses."
3. Sayings that sound deep. "At its core", "the real question is", "X is the language of Y", "결국 중요한 것은", "진정한 의미의".
4. Staged run-ups. "Here's the thing", "Simply put", "Honestly?", "솔직히 말씀드리면" before a routine claim.
5. Arguing with no one. "This isn't just about grades", "I'm not saying X, but", "물론 ~라고 생각할 수도 있지만" when nobody raised X.
6. Application templates. "I am writing to express my interest in", "What drew me to X is that", "As a researcher, I want to be the person who", "I am excited/thrilled to", "~라는 말이 있습니다" openings, "이러한 경험을 바탕으로 귀사에 기여하고자 합니다" closings, every paragraph ending in "~하고자 합니다".
7. Chatbot residue. "I hope this helps", "Certainly!", "Here is a revised version:" left inside the text.

## Fix when they pile up

8. Forced triads and symmetric pairs. "innovation, collaboration, and impact"; three parallel examples then a lesson; "People could use it to X, and machines could use it to Y." Use as many items as the meaning has.
9. Uniform rhythm. Every sentence 15 to 25 words, every paragraph claim, reason, tidy closure. Vary length; let some paragraphs end on a plain fact.
10. Inflation and sales words. pivotal, transformative, cutting-edge, passionate, dynamic, meaningful impact, journey, calling. 혁신적인, 새로운 지평, 끊임없이 성장, 한층 더 성장, 값진 경험, 소중한 경험.
11. Overused words (a cluster is the problem, one alone is not). EN: delve, leverage (figurative), robust (figurative), seamless, showcase, underscore, highlight (verb), crucial, meticulous, intricate, landscape, tapestry, testament, foster, navigate (figurative), spearhead, synergy. KR: 다양한, 효과적으로, 적극적으로, 끊임없는, 폭넓은, 깊이 있는, 역량, 시너지, 이를 통해, 이를 바탕으로, 뿐만 아니라.
12. Avoiding is/has. "serves as", "stands as", "boasts" become is, has. "~로서의 역할을 하다", "~을 지니고 있다" become "~이다", "~이 있다".
13. Vague outcomes. "significantly improved efficiency", "more accurate and more efficient", "좋은 성과를 거두었습니다" with no number or comparison. Flag and ask for the number; do not make one up.
14. Shallow -ing riders. "..., demonstrating my ability to lead." "~함으로써 리더십을 보여주었습니다." Keep only if the source supports the claim.

## Dense sentences

15. Inanimate subject, animate verb. "This experience taught me", "My curiosity led me to", "The project demanded", "The data told a different story". Put the person back: "I learned X during this project." Conventional pairs ("the results show") are fine.
16. Stacked nouns (3 or more). "real-time video model deployment pipeline" becomes "a pipeline for deploying video models in real time". Korean: "실시간 영상 생성 모델 배포 파이프라인 구축 경험", long "~의 ~의" chains, split into a verb phrase.
17. Rare coinages. "reader-patience budget", "taste debt". Use the ordinary phrase.
18. Ad hoc noun-to-verb. "I calendared it", "we sandboxed the idea". Use the plain verb.
19. Dropped optional words. Missing "that" after said/found/realized/believed when the clause is long, stacked reduced relatives ("the problem the team I joined spent a year on"). Restore when it helps parsing; do not restore every one.
20. Long dependencies. Subject far from its verb behind a list or parenthetical. Move the list after the verb or split the sentence. Korean: a long 관형절 before the noun ("제가 ~하면서 ~했던 ~ 프로젝트에서"), split into two sentences.

Korean 번역투 that comes with density: "이 경험은 저에게 ~을 가르쳐 주었습니다" becomes "이 경험에서 ~을 배웠습니다"; also "~에 의해", "~되어지다", "~를 가지고 있다", "~에 있어서", "~하는 것은 ~이다" cleft sentences.

## Formatting

21. Dashes. No em or en dashes in the final text unless the user's own sample uses them. In Korean, — is almost never human; always replace with a comma, period, colon, or parentheses.
22. Decoration. Bold labels on every bullet, emoji, Title Case headings.
23. Interpunct. No · for listing in Korean; use commas, 및, 와/과, or a slash.
24. Curly quotes (weak alone).

Weak alone (need company): stacked hedges, passive voice, a hyphen after the noun ("is high-quality"), a single dash, a single formal word.

## Register

Resume / CV bullets. Start with a plain past-tense verb (Built, Trained, Designed, Led). One result per bullet, with a number when the source has one. No "Responsible for", no self-adjectives (passionate, detail-oriented). Do not give every bullet the same three-clause shape.

Cover letters, SOPs, personal statements (EN). Open on the concrete thing (the problem, the result, the reason for this place), not on "I am writing to". One reason per paragraph. End on a fact or a plain statement of what you would work on, not a flourish.

Korean formal documents (자소서, 장학금, 지원서).
- First person '저/제', never '본인'.
- Active endings: '주도했습니다', '이끌었습니다', '만들었습니다'.
- Keep English technical terms inline (e.g. transformer, fine-tuning, API).
- Conjunctions such as '이후', '동시에', '무엇보다' where they connect real steps; do not start every sentence with one.
- No interpunct listing. Concise; cut filler sentences rather than polishing them.

Emails and messages. Lead with the ask or the answer. Skip boilerplate openers unless the relationship calls for one. If the reader already has the context, do not rebuild it before the point.

## What to keep

Specific or odd details, mixed feelings, a genuine aside, a first-person choice with its reason, quotations, names, titles, and anything inside code or URLs. Several patterns together are the signal; a careful writer may use any one on purpose.

## Do not overcorrect

No deliberate typos, slang, or mechanical sentence-length variation. Do not replace a banned word with a stranger one; rewrite the sentence. When the input already reads well, change as little as possible.

## Voice

If the user gives a sample of their own writing, read it first and match its sentence length, connectors, punctuation, and openings. The sample overrides the rules above, including the dash rule.

## Examples

Statement (EN)
Before: "My journey into robot learning wasn't just an academic pursuit — it was a calling. Over the past four years, I have delved into motion planning, reinforcement learning, and sim-to-real transfer, each experience deepening my passion for building robots that truly understand the world. This is where I want to make my mark."
After: "I have worked on robot learning for four years, mostly on motion planning, reinforcement learning, and sim-to-real transfer." + question: which one result should the next sentence name?
(The three areas stay because there really are three. The calling, the passion rider, and the closer go.)

Resume bullet
Before: "Spearheaded the development of a cutting-edge, scalable data pipeline, leveraging state-of-the-art techniques to drive significant improvements in throughput."
After: "Built a data pipeline that raised throughput from [a] to [b]." + question: what were a and b?

자소서 (KR)
Before: "이 경험은 저에게 단순히 기술적 역량을 넘어 협업의 진정한 의미를 일깨워 주었습니다. 다양한 배경의 팀원들과 적극적으로 소통하며 문제를 해결해 나갔고, 이를 통해 한층 더 성장할 수 있었습니다."
After: "이 프로젝트에서 기술 외에 협업하는 방법을 많이 배웠습니다. 전공이 다른 팀원들과 문제를 함께 풀었고, [그 과정에서 바꾼 것 한 가지]." + question: 구체적으로 무엇을 바꿨는지?
