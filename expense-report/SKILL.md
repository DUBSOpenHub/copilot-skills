---
name: expense-report
description: "Create and fill out Microsoft Dynamics 365 MyExpense expense reports from receipts using visible browser automation. Handles travel expenses, recurring monthly expenses (internet, phone), hotel itemization, and corporate AMEX matching. Produces a complete, review-ready draft; the user always submits themselves. Triggers include: 'expense report', 'submit expense', 'file an expense', 'internet expense', 'monthly expense', 'travel expense', or any request to log a reimbursable cost."
---

# /expense-report — MS Expense Automation

Automate expense report workflows in Microsoft Dynamics 365 Finance & Operations
Expense Management. Covers collecting receipts from multiple sources, creating
reports, adding expense lines (including hotel itemization and AMEX matching),
uploading receipts, and preparing for submission.

## Core Principles

- Work directly in the MyExpense tool UI (not a spreadsheet).
- Visible automation only (never headless).
- Default is to NOT submit the expense report.
- Never submit the report on the user's behalf.
- If the user asks you to submit:
  - Advise the user to review the report for accuracy and completeness.
  - Inform them the report is ready.
  - Recommend they submit it themselves directly in the expense tool.
- Be conservative and compliant.
- Prefer matching prior approved expense reports over inventing new interpretations.
- If something is ambiguous, make a reasonable assumption based on prior reports and proceed.
- Every expense line must have a receipt attached.
- Attach receipts while you are already inside each expense line (no second attachment pass).
- Hotels must always be itemized and the final hotel folio must always be attached.
- For hotel expenses, any food-related charges (meals, restaurant, minibar food, room service) must remain inside hotel itemization under Room Service & Meals (or equivalent).
- Do not assume meals have guests; only flag or ask if the receipt clearly suggests multiple people.
- Country or region must match where the expense occurred (e.g., USA, NOR, DNK) and currency must follow (USD, NOK, DKK).
- Never ask the user if an expense is personal; never auto-mark Personal Expense.
- Never try to set or change payment method; let the system assign it.
- Only use the default MyExpense URL. Only use another URL if the user explicitly provides and requests it; do not prompt.

## Step 1: Collect Receipts

Ask the user for receipt sources (one or more):

- Local files or folders
- Outlook emails (subject line or subject lines)
  - Receipts may be classic attachments or inline images embedded in the HTML body
- Teams messages (links)

**Outlook inline image handling:**

- Retrieve the full email body.
- Extract inline receipt images.
- Save as `email_<subject_snippet>_<date>_inline_<n>.png`.
- Treat identically to attachment receipts.

**Receipt parsing (for every receipt):**

- Extract vendor, date(s), amount, currency, country or region, and description clues.
- Detect hotel folios and itemization details when present.
- Deduplicate identical receipts.
- If unreadable, ask only for missing fields that block entry.

**Invoice date precedence (strict):**

1. Invoice created or invoice date
2. Due date only if no invoice date exists

## Step 2: Preview and confirm report setup BEFORE creation (ask once, hard stop)

- Navigate to Expense management.
- Click "+ New expense report" to open the new report creation panel/dialog.
- Do NOT create the report yet.

- Read and capture the prefilled values visible in the creation panel, including:
  - Interim approver
  - Final approver
  - Cost Center (CC) or Internal Order (IO)

- Infer the proposed report name and description from the receipts (based on Step 3 intent logic below):
  - Proposed report name
  - Proposed report description

- Inform the user of all proposed values in one message:
  - Interim approver: <prefilled>
  - Final approver: <prefilled>
  - Cost Center / IO: <prefilled>
  - Report name: <proposed>
  - Report description: <proposed>

- Ask exactly once:
  Based on the proposed approvers, CC/IO, report name, and description — do you want to proceed as-is, or would you like to change anything before I create the report?

- Stop and wait for the user's explicit response. Do NOT proceed automatically.

- If the user requests changes:
  - Apply changes in the creation panel (interim approver, final approver, CC/IO, report name, and/or description).

- If the user explicitly confirms to proceed as-is:
  - Keep the values unchanged.

- Only after the user explicitly confirms OR requested changes are applied:
  - Click "Create" to create the expense report draft.

## Step 3: Infer Report Intent

Infer report title and grouping from receipts:

- **Travel**: Use travel-style naming when travel patterns appear (flights, hotels, ground transport).
- **Recurring**: Use internet/phone-style naming for recurring invoices.
- **General**: Use a generic topic-plus-month format otherwise.

Keep descriptions brief and business-oriented.

## Step 4: Expense Line Descriptions

- Be clear but general.
- Do not list individual purchased items.
- For meals use:
  - Breakfast, Lunch, Dinner, Snack, Drink, or Meal
- If guests were present:
  - Description: "Meal with guests"
  - Guest details go only in the guest section.

## Step 5: Validation & Consistency

- Look at prior expense reports for the same expense type (e.g., internet, phone, travel).
- Use them as examples to ensure:
  - Correct expense category
  - Correct business justification
  - Correct formatting and structure
- If this is a recurring monthly expense, ensure the amount does not exceed what the user is allowed to expense per month.
- If prior reports show a consistent monthly amount, use that amount as the claimed expense (even if the receipt shows a higher value).

### Recurring Expense Detection (suggestion-only)

For expenses that appear recurring (phone bills, internet, subscriptions):

- Look at past expense reports and expense lines to detect recurring patterns:
  - Same vendor
  - Same or very similar amount
  - Same category
  - Regular cadence (e.g., monthly)
- If a clear recurring pattern exists: suggest reusing the previously expensed amount and category.
- Treat this as a suggestion, not an assumption.
- Do not ask the user to confirm unless there is a material mismatch between the receipt and the recurring pattern.

### Expense Categorization (authoritative)

- Before categorizing any expense line, look at prior expense reports to learn
  vendor-to-category patterns from the user's historical expenses.
- If a matching or near-matching vendor has been categorized before:
  - Reuse the previously used expense category.
- Only if no historical vendor-category pattern exists:
  - Apply the standard categorization rules below.

- When selecting from any drop-down list used for categorization in the MyExpense UI:
  - This applies to both:
    - The main Expense Category drop-down
    - Any subcategory drop-downs used during itemization (for example hotel itemization subcategories)
  - Open the drop-down list.
  - Scroll through the entire list at least once before selecting an option.
  - Only after reviewing the full list, select the option that best fits.
  - Do not select the first partial or "good enough" match without scanning the full list.

- Categorize as Ground Transportation:
  - Taxi
  - Rideshare (Uber, Lyft, Bolt)
  - Train
  - Bus
  - Tram
  - Metro / Subway
  - Ferry

- Explicit exclusions (NOT Ground Transportation):
  - Car rental (own category)
  - Fuel or charging (own category)
  - Parking fees (own category)
  - Tolls (appropriate toll/parking category)

## Site Details

- **Landing URL**: `https://aka.ms/msexpense`
- **Landing page title**: `Expense management -- Finance and Operations`
- **Report detail page title**: `Expense report -- Finance and Operations`
- **Framework**: Dynamics 365 Finance & Operations (SPA, React grids)
- If login, MFA, or workspace selection is required, pause only for required user interaction.

## Dynamics 365 Interaction Rules

These rules apply to ALL interactions in this app:

1. **Use `playwright-browser_type` with `slowly: true`** — bulk fill bypasses
   Dynamics' change handlers. Values appear visually but aren't registered.

   ```
   # Take snapshot to find element refs
   playwright-browser_snapshot
   # Click the field (triple-click to select existing value)
   playwright-browser_click → ref: <FieldName input ref>
   # Type slowly so Dynamics registers the value
   playwright-browser_type → ref: <FieldName input ref>, text: "value", slowly: true
   # Tab to confirm
   playwright-browser_press_key → key: Tab
   ```

2. **Use `data-dyn-controlname` selectors** — never `text=`. The `text=`
   selector matches hidden elements with similar labels (e.g., `text=New expense`
   matches the hidden "New expense report" button).

3. **Wait after every action** — `networkidle` is unreliable for Dynamics —
   background XHRs (telemetry, polling) keep it from resolving. After each
   action, take a snapshot and verify the expected element appeared:

   ```
   # After an action, wait and verify
   playwright-browser_wait_for → text: "Expected element text"
   playwright-browser_snapshot
   ```

4. **Combobox fields** — type partial text with `playwright-browser_type` (`slowly: true`)
   to filter, click the lookup button inside the control to open dropdown, click
   the matching row, then Tab to confirm.

5. **File uploads** — use `playwright-browser_choose_file` after clicking the
   upload button. The Dynamics upload control requires the file chooser pattern:

   ```
   # Click the browse/upload button to trigger file chooser
   playwright-browser_click → ref: <UploadControlBrowseButton ref>
   # Select the file
   playwright-browser_choose_file → paths: ["/path/to/file.pdf"]
   ```

6. **DOM readback** — element attributes may return empty after filling.
   Dynamics uses its own data binding. Use `playwright-browser_snapshot` to verify.

7. **Grids** — NOT standard `<table>`. Uses `fixedDataTable` React grid.
   - Rows: `[role="row"]` (first is header)
   - Cell values: nested `<input>` with `aria-label` = column name, `value` = data
   - Headers: `[role="columnheader"]`

8. **Dialogs** — `[role="dialog"]` is the notification panel, NOT form dialogs.
   Find form dialogs by ID prefix (e.g., `ExpenseNewExpenseReport_2_`).

9. **Dismiss overlays before major actions** — Dynamics pops notification panels
   and validation toasts that block clicks on underlying elements. Before clicking
   important buttons, take a snapshot and dismiss any visible close buttons
   (e.g., `SystemDefinedCloseButton`, `MessageBarCloseButton`).

## Checkpoint/Resume Pattern

The end-to-end flow (create report → add lines → set country → attach receipts →
verify) can be many steps. If a later step fails, do not restart from scratch.
After each major phase, save the checkpoint state so you can resume:

| Phase              | Checkpoint data                         | How to resume                                   |
| ------------------ | --------------------------------------- | ----------------------------------------------- |
| Report created     | Report URL from the browser             | Navigate directly to the report URL             |
| Expense line added | Report URL (line is attached to report) | Navigate to report URL, line is visible in grid |
| Receipt attached   | Report URL + receipt count from header  | Navigate to report URL, verify `ReceiptCount`   |

**Usage**: After completing each phase, log the checkpoint data. If a subsequent
phase fails, navigate back to the checkpoint URL rather than recreating the
report.

## Workflows

> **Design principle**: Steps describe _outcomes to achieve_, not exact click
> sequences. Selector hints (from `data-dyn-controlname` attributes) are
> provided as starting points — if a selector doesn't work, explore the DOM
> for alternatives rather than failing.

### 1. Create Expense Report

**Starting point**: Landing page (Reports tab)
**Goal**: Open the "new report" dialog, preview prefilled values with the user (per Step 2), fill in title/description, and create the report.

1. **Open new report dialog** — Click the "+ New expense report" button on the Reports tab toolbar. The dialog should contain a Title/Purpose field.
   - Hint: `[data-dyn-controlname="NewExpenseReportReportsTab"]`
2. **Read prefilled values** — Capture interim approver, final approver, and Cost Center/IO from the creation panel. Do NOT click Create yet.
3. **Preview with user** — Present all proposed values (per Step 2) and wait for explicit confirmation before proceeding.
4. **Fill Title/Purpose** — Enter the report name (inferred from Step 3: Infer Report Intent).
   - Hint: `#ExpenseNewExpenseReport_2_NamePurpose_input`
5. **Fill Description** (optional).
   - Hint: `#ExpenseNewExpenseReport_2_Description_textArea`
6. **Set "Include open expenses" to "Add none"** — The default is "Add all", which auto-attaches any existing unattached expenses. Set to "Add none" for a clean report.
7. **Click Create** — The page should navigate to the expense report detail page.
   - Hint: `[data-dyn-controlname="CreateButton"]`
8. **Verify** — Page title changes to `Expense report -- Finance and Operations`.

### 2. Add Expense Line

**Starting point**: Expense report detail page
**Goal**: Add a new expense line with category, date, amount, merchant, country, and currency. Repeat for each receipt.

For each receipt, determine whether it matches an imported corporate AMEX line or requires a new out-of-pocket line:

**Primary CC_Amex matching (deterministic):**

- Click "+ Unattached expense(s)" to view available transactions.
- Identify transactions with Payment Method = CC_Amex.
- Match parsed receipts to unattached CC_Amex transactions using:
  - Exact amount match
  - Exact same date match (using invoice date precedence)
- Select matched CC_Amex transactions and add them to the report.

**Secondary CC_Amex proximity check (ask once):**

- Identify remaining CC_Amex transactions that are within ±3 days of any receipt date.
- Present a list showing: transaction date, amount and currency, merchant.
- Ask exactly once whether the user wants to pull any of these transactions into the report to attach receipts.
- Import only the transactions explicitly selected by the user.

**For imported CC_Amex lines:**

- Open the expense line.
- Attach the receipt immediately while in the line.
- Add a brief description.
- **Never change amount, date, vendor, or payment method on imported AMEX lines.**

**For new out-of-pocket lines:**

1. **Open new expense form** — Click the "New expense" button in the expense grid toolbar. The category field should appear.
   - Hint: `[data-dyn-controlname="NewExpenseButton"]`
2. **Set Category** — This is a combobox: type partial text to filter, open the lookup dropdown, and click the matching row.
   - Hint: `[data-dyn-controlname="CategoryInput"]`
   - Selecting a category auto-fills Payment method and Currency.
3. **Fill Date** — Use the invoice date per the precedence rules in Step 1. Triple-click to select existing value, type the date, then Tab.
   - Hint: `[data-dyn-controlname="DateInput"] input`
4. **Fill Amount** — Use the receipt amount (or the recurring cap from Step 5 if applicable). Never change imported AMEX amounts.
   - Hint: `[data-dyn-controlname="AmountInput"] input`
5. **Fill Merchant**.
   - Hint: `[data-dyn-controlname="MerchantInputNoLookup"] input`
6. **Fill Description** (optional) — Keep brief and business-oriented.
   - Hint: `[data-dyn-controlname="NotesInput"] textarea`
7. **Save** — Wait for spinner to disappear and check for red validation icons.
   - Hint: `[data-dyn-controlname="SaveButton"]`
8. **Set Country/region** — Must match where the expense occurred. This field is blank by default on manually-created lines and triggers a validation error if not set. Setting it recalculates the net amount (applies local VAT rules).
   - Hint: `[data-dyn-controlname="TrvExpTrans_CountryRegion"] input`
9. **Verify currency** — Currency must match the country/region (e.g., USD for USA, NOK for NOR, DKK for DNK). If auto-filled incorrectly, correct it.
10. **Verify** — No red validation icons remain.

**Meals:**

- Default is solo dining.
- Only ask about guests if the receipt strongly suggests multiple people (e.g., large party, itemized for multiple diners).

### 3. Hotel Itemization (mandatory for hotel expenses)

**Starting point**: Expense report detail page with hotel expense line added
**Goal**: Itemize hotel charges and attach the final hotel folio.

Hotels must **always** be itemized. Do not proceed until itemization and receipt attachment are complete.

1. **Open the hotel expense line** for editing.
2. **Itemize into separate sub-lines:**
   - Nightly room rate (one line per night, or combined if same rate)
   - Taxes
   - Other charges shown on the folio (parking, minibar, etc.)
3. **Food charges on hotel folio:**
   - All hotel food charges (meals, restaurant, minibar food, room service) must remain inside hotel itemization under Room Service & Meals (or equivalent).
   - **Never** bundle into the room rate or separate out as standalone expense lines.
4. **Attach the final hotel folio** to the hotel expense line using Workflow 4 (Attach Receipt).
5. **Verify** — All sub-lines sum to the folio total, folio is attached, no validation errors.

### 4. Attach Receipt

**Starting point**: Expense report detail page with expense line selected
**Goal**: Open the receipts pane, upload a file, and close the pane.

1. **Open receipts pane** — Click "Edit" in the Receipts section. The "+ Add receipts" button should appear.
   - Hint: `[data-dyn-controlname="EditReceipts"]`
2. **Add receipt** — Click "+ Add receipts".
   - Hint: `[data-dyn-controlname="AddButton"]`
3. **Upload file** — Use `playwright-browser_choose_file` after clicking the browse button.
   - Hint: `[data-dyn-controlname="UploadControlBrowseButton"]`
4. **Fill receipt name** (optional) — Give the receipt a descriptive name.
5. **Click Upload** — A success banner ("File uploaded as '...'") should appear.
   - Hint: `[data-dyn-controlname="UploadControlUploadButton"]`
6. **Verify the receipt is attached** before moving on to the next expense line.
7. **Click OK** to confirm, then **close the receipts pane**.
   - Hints: `[data-dyn-controlname="OkButtonAddNewTabPage"]`, `[data-dyn-controlname="CloseButton"]`

### 5. Final Verification (always)

**Starting point**: Expense report detail page with all expense lines and receipts attached
**Goal**: Verify everything looks correct and inform the user the report is ready.

1. **Verify every expense line** — Confirm category, date, amount, merchant, country, and currency are all set with no red validation icons.
2. **Verify every receipt** — Confirm the receipt count in the header matches the number of expense lines. Every line must have a receipt.
3. **Verify hotel itemization** — If hotel expenses exist, confirm itemization is complete and folio is attached.
4. **Verify country/region and currency consistency** — Each line's currency matches its country/region.
5. **Verify totals** — Totals look reasonable and duplicates are resolved.
6. **Stop and inform the user** — Tell the user whether the report is ready for their review. Do NOT click Submit.

## Page Map

### Landing page: Expense management

- **Title**: `Expense management -- Finance and Operations`
- **Tabs**: Reports (default), Receipts, Expenses
- **Reports grid columns**: Expense report number, Purpose, Amount, Receipts attached, Approval status, Invoice, Payment voucher, Payment date
- **Report statuses**: Draft, In review, Processed for payment
- **Report number pattern**: D17930000XXXXXX (clickable hyperlink, class `dyn-hyperlink`)
- **Toolbar**: New expense report (`NewExpenseReportReportsTab`), Delete, Submit, Recall, Copy, View history

### Expense report detail page

- **Title**: `Expense report -- Finance and Operations`
- **Header fields**: `ToBePaidTotal`, `ReceiptCount`, `ReportStatus`
- **Tabs**: Expenses, Receipts
- **Expense grid toolbar**: New expense (`NewExpenseButton`), Unattached expenses, Remove, Bulk edit, Copy
- **Detail panel** (right side): amount, date, category, merchant, payment method, Country/region (`TrvExpTrans_CountryRegion`), Net amount (`TrvExpTrans_NetTransactionAmount`), Description (`TrvExpTrans_AdditionalInformation`)
- **Policy**: "SEE POLICY" button, red error icon = violation (e.g., missing receipt)

## Receipts Tab — Receipt-to-Expense Matching

### Key Controls

- `ReceiptThumbnail`: Receipt cards in left panel (click to select)
- `CardGroup_Receipts`: Right panel showing selected receipt filename
- `MatchedExpensesGrid_Receipts`: Grid showing matched expense lines for selected receipt
- `MatchExpensesButton`: Opens "Attach to expense" dialog with unmatched expense lines
- `RemoveButton`: Inside matched expense rows

### CRITICAL WARNING: RemoveButton is destructive

The `RemoveButton` in the `MatchedExpensesGrid_Receipts` **DELETES THE RECEIPT FROM THE REPORT**, not just the match association. **NEVER** use RemoveButton to "detach" a receipt from a wrong expense line — it will permanently remove the receipt file.

### Matched Grid Value Format

Input values in the matched grid are combined: `"M/D/YYYY | amount | Merchant"` (e.g., `"12/1/2023 | 50.00 | Contoso Ltd"`). Extract dates with regex `/^(\d{1,2}\/\d{1,2}\/\d{4})/`.

### Receipt List Behavior

- Displayed in 2-column thumbnail grid with pagination (25 per page)
- **Receipt order is unstable** — indices change between clicks and operations
- Identify receipts by filename (from `CardGroup_Receipts` panel), not by index
- Duplicate uploads can exist (same file uploaded multiple times)
- Use `playwright-browser_evaluate` for clicks to avoid ShellBlockingDiv interception

### Attach to Expense Dialog

- Grid ID changes each session (e.g., `MainGrid_5474_0_grid`)
- Uses virtual scrolling — only ~6-7 rows visible at a time
- Arrow key navigation needed for off-screen rows
- Dialog auto-closes if only one unmatched expense line remains
- Only shows expense lines not yet matched to any receipt

### Workflow: Match Receipt to Expense (Recommended)

**Starting point**: Expense report detail page with receipts uploaded
**Goal**: Match each receipt to its corresponding expense line from the Receipts tab.

This workflow is more reliable than attaching receipts from the Expenses view because it clearly shows which receipt you're working with.

1. **Switch to Receipts tab** — Click the "Receipts" tab in the expense report.
   - Hint: Look for tab selector or `Receipts` text link

2. **Select a receipt** — Click on a receipt thumbnail in the left panel. The right panel shows the filename in `CardGroup_Receipts`.
   - Verify the correct receipt is selected by checking the filename

3. **Click "Match expenses"** — Opens the "Attach to expense" dialog showing unmatched expense lines.
   - Hint: `[data-dyn-controlname="MatchExpensesButton"]`

4. **Select the matching expense line** — The dialog grid shows expense lines as `"M/D/YYYY | amount | Merchant"`. Click the row that matches this receipt's date.
   - Use arrow keys to navigate if the row is not visible (virtual scrolling)

5. **Confirm selection** — Click Attach/OK in the dialog. The receipt now appears in `MatchedExpensesGrid_Receipts` for that expense line.

6. **Repeat for remaining receipts** — Go back to step 2 for each unmatched receipt.

7. **Verify all matches** — Check each expense line in the Expenses tab to confirm receipts are attached (policy violation icons should clear).

**Note**: If you match a receipt to the wrong expense line, you must re-upload the receipt and match again. Do NOT use RemoveButton — it deletes the receipt entirely.

## Error Handling

| Issue                                        | Action                                                                                                                         |
| -------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| Validation error on save (red icon)          | Check Country/region is set; check required fields                                                                             |
| Receipt deleted instead of detached          | RemoveButton in MatchedExpensesGrid DELETES the receipt. Never use it to fix wrong matches. Re-upload deleted receipts instead |
| ShellBlockingDiv intercepts clicks           | Use `playwright-browser_evaluate` to click elements directly. Wait for blocking div to disappear                               |
| Receipt list indices shift                   | Never rely on thumbnail index — always verify receipt identity by reading filename from CardGroup_Receipts panel               |
| Category lookup shows no results             | Type fewer characters; verify category name spelling                                                                           |
| Receipt upload button unresponsive           | Use `playwright-browser_choose_file` after clicking the browse button                                                          |
| "Save and close" navigates away unexpectedly | You're clicking the report-level button, not a pane close button                                                               |
| `text=` selector timeout                     | Switch to `[data-dyn-controlname="..."]` selector                                                                              |
| Session expired / login redirect             | Check the current URL for auth domain redirect; prompt user to re-authenticate in the browser                                  |
| Currency mismatch after setting country      | Verify currency matches country/region; correct manually if auto-fill is wrong                                                 |
| AMEX line amount differs from receipt        | Never change imported AMEX amounts; flag discrepancy to the user                                                               |
