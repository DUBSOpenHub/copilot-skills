# Final Exam (Template)

15-20 questions covering all modules. Use `ask_user` with 4 choices each.

## Instructions for the Skill

- Show "🛡️ [MODULE TITLE] — Final Exam" header
- Present questions via `ask_user` with 4 choices
- Track in `soss_quiz_results` with module='final-exam'
- Show running score every 5 questions
- Final score out of N with percentage

## Scoring

```
100%:    🏆 PERFECT — "Module Master" badge + 300 XP
90-99%:  🥇 EXCELLENT — 250 XP
70-89%:  🥈 PASSED — 200 XP
50-69%:  🥉 CLOSE — 100 XP + review recommendations
< 50%:   📚 NEEDS REVIEW — 50 XP + restart recommendation
```

## Questions

### Module 0 (2 questions)
1. [Question] a) Correct ✅ b) Wrong c) Wrong d) Wrong
2. [Question] a) Correct ✅ b) Wrong c) Wrong d) Wrong

### Module 1 (3+ questions)
3-5. [Questions covering Module 1 content]

<!-- Continue for all modules, 2-3 questions per module -->

Log all answers and emit exam event to `soss_dashboard`.
