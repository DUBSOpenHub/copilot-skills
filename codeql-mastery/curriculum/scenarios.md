# Scenario Challenges

Present these as real-world situations. Ask the learner what they would do.
Use `ask_user` with choices for each step.

## Scenario 1: First-Day Security Setup
> You just joined a team and have been given access to the main application repository. Your security lead says "Get code scanning running by end of day." The repo is a Python/JavaScript monorepo with no security features enabled.

**Answer path:**
1. Go to Settings → Code security and analysis
2. Enable code scanning with Default Setup
3. Verify both Python and JavaScript are detected
4. Check the Security tab after the first scan completes
5. Review any initial alerts

## Scenario 2: Alert Triage Under Pressure
> Code scanning found 47 alerts after the first scan. Your manager asks "How bad is it?" You need to prioritize and report.

**Answer path:**
1. Filter alerts by severity (Critical → High → Medium → Low)
2. Focus on `error` severity with high security-severity scores (8.0+)
3. Check if critical alerts are in active code paths (not dead code)
4. Report: number by severity, top vulnerability types, estimated fix effort
5. Create issues for critical/high items, batch medium/low for next sprint

## Scenario 3: False Positive Investigation
> A developer on your team says "Code scanning flagged my PR but it's a false positive — the input is already validated." How do you verify?

**Answer path:**
1. Look at the alert's data flow path (source → sink)
2. Check if there's a sanitizer between source and sink
3. If validated: dismiss the alert as "Used in tests" or "Won't fix" with explanation
4. If NOT validated: the alert is real — the "validation" might not cover all cases
5. Consider adding a CodeQL model extension if the sanitizer is custom

## Scenario 4: Custom Query Request
> Your security team discovered that your internal framework has a custom SQL execution method called `db.rawQuery()` that CodeQL doesn't know about. Vulnerabilities through this method aren't being detected.

**Answer path:**
1. Write a custom CodeQL query that models `db.rawQuery()` as a SQL sink
2. Or create a model extension (data extension YAML) to tell CodeQL about it
3. Test the query/model against known vulnerable code
4. Package it as an organization query pack
5. Add it to the code scanning configuration

## Scenario 5: Community Pack Evaluation
> Your team wants to add the security-extended query suite. The current scan uses the default suite with zero false positives. The security team wants broader coverage but the dev team is worried about alert fatigue.

**Answer path:**
1. Run security-extended on a branch first (not main) to preview new alerts
2. Count additional findings: how many are real vs. false positives
3. If FP rate is acceptable (< 20%), switch to security-extended
4. If too many FPs, keep default and add specific community packs for high-value checks
5. Set up alert dismissal workflow for known FPs

## Scenario 6: Securing an Open-Source Project
> You maintain a popular open-source library. A SOSS Fund reviewer asks you to demonstrate security tooling. You need to show code scanning is active, community packs are in use, and you can explain your vulnerability management process.

**Answer path:**
1. Show code scanning is enabled (Security tab → Code scanning alerts)
2. Show the query suite in use (default or security-extended)
3. Demonstrate alert triage: how you handle, fix, or dismiss alerts
4. Show any custom queries for your project's specific patterns
5. Export security posture data for the SOSS Fund dashboard

## Scenario 7: Database Debugging
> Your code scanning workflow keeps failing for a Java project with the error "Build failed during CodeQL extraction." How do you fix it?

**Answer path:**
1. Check the Actions workflow log for the specific build error
2. CodeQL for compiled languages (Java) must observe a successful build
3. Ensure the build environment has all dependencies (Maven/Gradle, JDK version)
4. Try setting the `build-mode` to `autobuild` or specifying a custom build command
5. If build is complex, consider using `manual` build mode with explicit build steps

## Scenario 8: Cross-Language Vulnerability
> Your application has a Python API that generates SQL queries, which are passed to a Go microservice that executes them. Code scanning finds the vulnerability in neither individual language analysis.

**Answer path:**
1. Understand the limitation: CodeQL analyzes one language at a time
2. The taint flow crosses a language boundary (Python → Go) which CodeQL can't track
3. Mitigations: parameterize queries in the Python layer before sending
4. Add a custom CodeQL query in Go that treats all incoming API data as tainted
5. Consider API contract testing as an additional defense layer
