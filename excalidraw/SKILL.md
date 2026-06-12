---
name: excalidraw
description: Generate Excalidraw diagrams from descriptions. Creates .excalidraw JSON files that can be opened in https://aka.ms/excalidraw or embedded in documentation. Use when creating architecture diagrams, flowcharts, data flow visualizations, or illustrations for proposals and design documents.
---

# Excalidraw JSON Format

When generating Excalidraw `.excalidraw` files programmatically, follow these requirements.

## File Structure

```json
{
  "type": "excalidraw",
  "version": 2,
  "source": "claude",
  "elements": [...],
  "appState": {"viewBackgroundColor": "#ffffff"}
}
```

## Critical: Text Elements Require Explicit Dimensions

**Text elements MUST have `width` and `height` properties**, otherwise they render as 0-size invisible boxes.

```json
{
  "type": "text",
  "x": 50,
  "y": 20,
  "width": 600,
  "height": 35,
  "text": "Your text here",
  "fontSize": 28,
  "fontFamily": 1,
  "strokeColor": "#000000",
  "id": "unique_id",
  "textAlign": "left",
  "verticalAlign": "top"
}
```

### Dimension Guidelines

- Estimate `width` based on text length and fontSize (~10-12px per character at fontSize 14)
- Estimate `height` based on fontSize and line count: **use `fontSize * 2.5 * lineCount`** to avoid truncation
  - The Virgil hand-drawn font (fontFamily: 1) needs extra vertical space
  - This is much more generous than typical font metrics but necessary for proper display
  - Example: 4 lines at fontSize 12 → height of `12 * 2.5 * 4 = 120`
  - Single line title at fontSize 28 → height of `28 * 2.5 = 70`
- For multi-line text, use `\n` in the text string
- When in doubt, round height UP significantly - slightly too large is far better than truncated

## Common Element Types

### Rectangle (Leaf Element with Fill)

```json
{
  "type": "rectangle",
  "x": 30,
  "y": 70,
  "width": 200,
  "height": 100,
  "strokeColor": "#1864ab",
  "backgroundColor": "#a5d8ff",
  "fillStyle": "hachure",
  "strokeWidth": 1,
  "roundness": { "type": 3 },
  "id": "unique_id"
}
```

### Rectangle (Container - Transparent)

```json
{
  "type": "rectangle",
  "x": 20,
  "y": 50,
  "width": 300,
  "height": 400,
  "strokeColor": "#1864ab",
  "backgroundColor": "transparent",
  "fillStyle": "solid",
  "strokeWidth": 2,
  "roundness": { "type": 3 },
  "id": "container_id"
}
```

### Ellipse

```json
{
  "type": "ellipse",
  "x": 100,
  "y": 100,
  "width": 150,
  "height": 80,
  "strokeColor": "#2f9e44",
  "backgroundColor": "#b2f2bb",
  "fillStyle": "hachure",
  "strokeWidth": 2,
  "id": "unique_id"
}
```

### Arrow

```json
{
  "type": "arrow",
  "x": 200,
  "y": 150,
  "width": 100,
  "height": 50,
  "strokeColor": "#2f9e44",
  "strokeWidth": 2,
  "points": [
    [0, 0],
    [100, 50]
  ],
  "id": "unique_id"
}
```

### Arrow Bindings

To anchor arrows to shapes:

```json
{
  "startBinding": { "elementId": "source-id", "focus": 0, "gap": 1 },
  "endBinding": { "elementId": "target-id", "focus": 0, "gap": 1 }
}
```

## Styling: Color-Coded Sections with Transparent Containers

Use color to differentiate logical sections, but keep it tasteful:

### Critical Rule: Container Boxes Must Be Transparent

**Any box that contains other elements (wrapper/container boxes) MUST have `"backgroundColor": "transparent"`.**

Only leaf elements (boxes that don't contain other boxes) should have fills. This prevents visual clutter and ensures inner elements remain visible.

```json
// GOOD: Container box is transparent
{
  "type": "rectangle",
  "id": "container",
  "strokeColor": "#1864ab",
  "backgroundColor": "transparent",
  "strokeWidth": 2
}

// GOOD: Inner leaf box has fill
{
  "type": "rectangle",
  "id": "inner_item",
  "strokeColor": "#1864ab",
  "backgroundColor": "#a5d8ff",
  "fillStyle": "hachure"
}
```

### Recommended Color Palette (Open Color)

Use matching border and fill colors per section:

| Section Type | Border    | Fill (light) | Use Case              |
| ------------ | --------- | ------------ | --------------------- |
| Blue         | `#1864ab` | `#a5d8ff`    | Data sources, inputs  |
| Orange       | `#e67700` | `#fff3bf`    | Processing, signals   |
| Purple       | `#862e9c` | `#f3d9fa`    | Graphs, relationships |
| Green        | `#2f9e44` | `#b2f2bb`    | Core logic, ML/AI     |
| Teal         | `#0c8599` | `#99e9f2`    | Outputs, consumers    |
| Gray         | `#495057` | `#dee2e6`    | Neutral, annotations  |

### FluentUI-Aligned Colors (for Microsoft Projects)

For diagrams in Microsoft/FluentUI contexts, use these colors for design consistency:

| Purpose       | Stroke    | Background | Notes                    |
| ------------- | --------- | ---------- | ------------------------ |
| Primary/Brand | `#0078D4` | `#CFE4FA`  | Microsoft Blue           |
| Success       | `#107C10` | `#DFF6DD`  | Green for positive flows |
| Error/Danger  | `#D13438` | `#FDE7E9`  | Red for errors           |
| Warning       | `#F7630C` | `#FFF4CE`  | Orange for caution       |
| Accent        | `#5C2D91` | `#E8DAEF`  | Purple for emphasis      |
| Neutral       | `#1e1e1e` | `#F3F2F1`  | Default                  |

### Text Color: Always Black

**All text elements MUST use `"strokeColor": "#000000"` (black).** Colored text on hachure-filled backgrounds is hard to read. Use box border/fill colors to convey grouping, not text color.

### What to Avoid

- Colored text on filled boxes (use black text instead)
- Filling container/wrapper boxes (makes inner elements hard to see)
- Mismatched border and fill color families
- Too many different colors in one diagram (stick to 3-5 section colors max)

## Font Families

- `1` = Virgil (hand-drawn style, default)
- `2` = Helvetica
- `3` = Cascadia (monospace)

## Bound Text (Container Labels)

To make text scale with its container, bind text to a shape:

1. Add `boundElements` array to the container:

```json
{
  "type": "rectangle",
  "id": "my_box",
  "boundElements": [{"type": "text", "id": "my_box_text"}],
  ...
}
```

2. Add `containerId` to the text element:

```json
{
  "type": "text",
  "id": "my_box_text",
  "containerId": "my_box",
  "textAlign": "center",
  "verticalAlign": "middle",
  ...
}
```

### Bound Text Notes

- Text alignment typically uses `"center"` and `"middle"` for bound text
- The container will auto-resize based on text content when edited
- Works with rectangles, ellipses, diamonds, and other shapes

## Best Practices

1. Use unique `id` values for all elements
2. Position elements on a grid (multiples of 10 or 20)
3. Keep consistent spacing between related elements
4. Use color coding to group related concepts (matching border + fill per section)
5. **Container boxes must be transparent** - only fill leaf elements
6. **All text must be black** (`#000000`) - use box colors for grouping, not text colors
7. Add key insight boxes at the top of diagrams with distinctive styling
8. Include token counts or metrics on arrows to show data flow
9. **Prefer bound text** for labels inside shapes - this ensures text scales with containers
10. For standalone text (not in shapes), use very generous `height` values: `fontSize * 2.5 * lineCount`

## Loading and Exporting via Browser

Use the Microsoft internal Excalidraw instance (`https://aka.ms/excalidraw`). Do NOT use `excalidraw.com` — it violates compliance rules.

### Important: CSP restrictions

The MS-internal Excalidraw instance (`aka.ms/excalidraw`, hosted on `jolly-ground-0a6b3831e.4.azurestaticapps.net`) has strict Content Security Policy headers that **block `fetch()` to `127.0.0.1` and `localhost`**. Do NOT use a local HTTP server as a data bridge — it will fail with CSP violations.

### Loading a diagram into Excalidraw

Use Playwright's native `fileChooser` event combined with a `showOpenFilePicker` override. This bypasses CSP entirely because no network requests are made.

#### Why the override is needed

- Excalidraw uses the **File System Access API** (`showOpenFilePicker`/`showSaveFilePicker`), not `<input type="file">` — so `browser_file_upload` does not work directly.
- **DragEvent drop** is rejected by Excalidraw with "Couldn't load invalid file" — do not attempt drag-and-drop.
- The override converts the File System Access API call into a hidden `<input type="file">` that Playwright's `fileChooser` event can intercept.

**CRITICAL**: The MS Excalidraw instance does NOT show a "Load from file" confirmation dialog. Clicking the Open button directly invokes `showOpenFilePicker`. Therefore the override MUST be set up BEFORE the Open button is clicked, and everything must happen in a single `browser_run_code` call.

#### Step-by-step flow

1. **Navigate** to `https://aka.ms/excalidraw` and wait for it to load (SSO signs in automatically):

   ```
   browser_navigate to https://aka.ms/excalidraw
   Wait ~5 seconds for SSO + canvas to load
   ```

   If SSO doesn't auto-complete (e.g. "Pick an account" screen appears), click the user's account to finish sign-in, then wait for the canvas to load.

2. **Load the file in a single atomic `browser_run_code` call** — override `showOpenFilePicker`, then click menu → Open, and catch the file chooser:

   ```javascript
   async (page) => {
     // Step 1: Override showOpenFilePicker BEFORE any menu clicks
     await page.evaluate(() => {
       window.showOpenFilePicker = () => {
         return new Promise((resolve) => {
           const input = document.createElement("input");
           input.type = "file";
           input.accept = ".excalidraw,.json";
           input.style.display = "none";
           input.addEventListener("change", () => {
             const file = input.files[0];
             resolve([{ getFile: async () => file }]);
             input.remove();
           });
           document.body.appendChild(input);
           input.click();
         });
       };
     });

     // Step 2: Click the hamburger menu
     await page.locator('[data-testid="main-menu-trigger"]').click();
     await page.waitForTimeout(800);

     // Step 3: Click Open and catch the file chooser simultaneously
     const [fileChooser] = await Promise.all([
       page.waitForEvent("filechooser", { timeout: 10000 }),
       page.locator('[data-testid="load-button"]').click(),
     ]);

     // Step 4: Set the file
     await fileChooser.setFiles("/absolute/path/to/diagram.excalidraw");
     await page.waitForTimeout(3000);
     return "Loaded!";
   };
   ```

3. **Scroll to content and frame the diagram** — the diagram loads off-screen. Use `browser_snapshot` to check for a "Scroll back to content" button and click it. Then zoom out using the zoom-out button (`button[aria-label="Zoom out"]`) repeatedly until the full diagram fits in the viewport. **Do NOT use `Ctrl+Shift+1`** — this shortcut does not work on the MS Excalidraw instance. There is also no public `window.excalidrawAPI` available for programmatic zoom.

### Exporting to PNG/SVG

#### Quick export (recommended): Screenshot

After loading the diagram, click "Scroll back to content" to center it, then use `browser_take_screenshot` to capture a PNG. This includes UI chrome but is fast and reliable:

```
browser_take_screenshot with filename "diagram.png"
```

#### Full export (no UI chrome)

Override `showSaveFilePicker` to capture the exported binary, then use Playwright's `run_code` to write it to disk:

```javascript
async (page) => {
  // Set up a promise to capture the exported data
  await page.evaluate(() => {
    window._exportedData = null;
    window._exportReady = new Promise((resolve) => {
      window._exportResolve = resolve;
    });
    window.showSaveFilePicker = async (opts) => ({
      createWritable: async () => {
        const chunks = [];
        return {
          write: async (data) => {
            const buf = data instanceof Blob ? new Uint8Array(await data.arrayBuffer()) : data;
            chunks.push(buf);
          },
          close: async () => {
            const total = chunks.reduce((s, c) => s + c.length, 0);
            const merged = new Uint8Array(total);
            let off = 0;
            for (const c of chunks) {
              merged.set(c, off);
              off += c.length;
            }
            // Store as base64 for retrieval
            let binary = "";
            for (let i = 0; i < merged.length; i++) binary += String.fromCharCode(merged[i]);
            window._exportedData = btoa(binary);
            window._exportResolve();
          },
        };
      },
    });
  });

  // Click: menu → "Export image..." → "Export to PNG"
  await page.locator('[data-testid="main-menu-trigger"]').click();
  await page.locator('[data-testid="image-export-button"]').click();
  await page.locator('[aria-label="Export to PNG"]').click();

  // Wait for export and retrieve the base64 data
  await page.evaluate(() => window._exportReady);
  const b64 = await page.evaluate(() => window._exportedData);

  // Write to disk (b64 is returned to the caller for saving via bash)
  return b64;
};
```

Then save the base64 data to a file using Node (cross-platform — works on macOS, Linux, and Windows):

```bash
node -e "require('fs').writeFileSync('diagram.png', Buffer.from(process.argv[1], 'base64'))" "<base64_data>"
```

**Note:** If the base64 string is very large, the `browser_run_code` return value may be truncated. In that case, retrieve the data in chunks to avoid size limits:

```javascript
// After export is ready, retrieve in chunks:
const size = await page.evaluate(() => window._exportedData.length);
const CHUNK = 50_000;
let out = "";
for (let start = 0; start < size; start += CHUNK) {
  out += await page.evaluate(([s, c]) => window._exportedData.slice(s, s + c), [start, CHUNK]);
}
// Then save: node -e "require('fs').writeFileSync('diagram.png', Buffer.from(process.argv[1], 'base64'))" "$out"
```

If chunked retrieval still fails, `browser_take_screenshot` can be used as a last resort (note: this includes UI chrome).

### Preserving Source Files

Always save the `.excalidraw` file alongside any converted PNG/SVG for future editing.
