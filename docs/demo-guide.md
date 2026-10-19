# Demo Guide: Showing MarketingIQ to the Performance Marketing Manager

A plan for a 15-minute meeting. The goal isn't to impress with a chatbot. It's to show an assistant whose numbers can be trusted and checked, which says what it doesn't know, and which has a careful path to real data. Then to leave with answers to the questions only the manager can give.

## Before the meeting (the day before)

1. **Start it and check it.** `uv run uvicorn marketingiq.api.app:app`, open `http://127.0.0.1:8000/`, and ask one question to confirm the model key works.
2. **Ask the demo questions in advance.** Answers take 10 to 30 seconds on the free tier, sometimes longer, and the free model can occasionally be unavailable. Ask every question below beforehand, read each answer, and re-ask any that came out wrong or muddled. In the meeting, open them from **Recent questions**: they appear instantly, with their evidence. Ask one live, to show it's real.
3. **Have a fallback.** If the provider is down, the stored answers still open, and the terminal (`python -m marketingiq.assistant`) shows the same thing.
4. **Bring** the [build journal](build-journal.md)'s checklist and this guide.

## The flow

| Minutes | Show | Question to ask the assistant | Point to make |
|---|---|---|---|
| 0–2 | The page and its banner | – | "Everything you'll see is a fictional business built to behave like ours: the same channels, forms, lead types and tracking gaps. No company data was used." |
| 2–5 | A plain answer and its evidence | Which campaigns brought in the most qualified new-customer leads last month? | Hover a number: it shows the tool call and the exact place it came from. **The model can't type a number.** Point out the caveat: most leads can't be tied to a campaign at all. |
| 5–7 | Attribution, honestly | How much credit does retargeting get under each attribution model over the past year? | The same leads get different credit under different rules. "Credit isn't cause": only a holdout test shows whether retargeting adds leads. |
| 7–9 | Sources that never agree | How do Meta's reported leads compare with the leads in Salesforce, campaign by campaign, last month? | Meta counts view-throughs and can't see phone calls. The assistant compares the sources and never adds them. |
| 9–11 | It says "I can't tell" | Did the location-page redesign change how often visitors submit a form? | The answer is "no detectable change": at this traffic, chance alone moves the rate by about 20%. Most dashboards would show a confident +21%. |
| 11–12 | It refuses, and it asks | List the phone numbers of the leads from Barrie. Then: How is the furnace campaign doing? | It refuses contact details. For an ambiguous name it asks which campaign you mean; reply "the lead form promo" to continue the conversation. |
| 12–13 | Broken tracking is not a bad month | What can't we conclude about July 2026? | It finds a week where form tracking broke, from the data alone, and says fewer attributed leads that week means broken tracking, not fewer customers. |
| 13–15 | What real data would take | – | The four approval gates, the privacy work (hidden counts can be recovered by subtraction, so real data needs noise: ADR-007), and the questions below. |

## Questions to ask the manager

These replace guesses in [`unverified-register.md`](unverified-register.md). None involves sharing data.

- Do we run Google Ads, and can its spend be exported? (U-10)
- Do the quote and callback forms send UTMs and the GA client ID into Salesforce as hidden fields? (U-06)
- Is there call tracking for phone leads? (U-08)
- Is the GA4 export to BigQuery switched on? Its history can't be recovered later. (U-09)
- What does "qualified" mean in our Salesforce, and is stage history tracked? (U-02, U-03)
- Roughly how many leads a month does a typical campaign get? (This decides how useful campaign-level answers are once small counts are hidden.)
- Does this rule match how you'd spot a weak campaign: cost per lead below the median, and qualification rate below the median? (Question 6)
- Who would run a privacy review, if we wanted to try this on real data? (U-15)
- Which questions do you answer by hand every month? (They should become benchmark cases.)

## Likely questions, and honest answers

**"How accurate is it?"** On the fictional data, every number the tools produce matches an independent second implementation (663 checked). The assistant's answers pass 22 of 32 test questions, and 8 of 12 questions it was never tuned on. The misses are mostly incomplete answers or a mixed-up source; none contained an invented number. A larger model would likely do better, but the free tier couldn't serve one reliably.

**"Why not just put our exports into ChatGPT?"** A general chatbot calculates its own numbers, can't show where they came from, doesn't know our definitions (what counts as a new-customer lead, which sources overlap), and would receive raw customer records. Here the numbers come from defined calculations, the model only sees totals, and every figure is traceable.

**"What would it cost?"** The demo runs on a free tier, which is fine only because the data is fictional. Real data needs an approved, paid provider that doesn't train on our data. That cost is small next to the approvals and the data work.

**"How long until it works on our data?"** It depends on the approvals, not the code: the R0 to R3 gates in the README. The first useful step needs no approval at all: answer the questions above.

**"So retargeting works?"** It gets credit because it reaches people who were already likely to enquire. Whether it adds leads can only be measured with a holdout test, and the assistant says so instead of guessing.

## What not to claim

- That the company uses it, or that it improved any result.
- That it's accurate on real data: it has only seen fictional data.
- That the scores are final: they come from one small free model, on a small set of questions.
