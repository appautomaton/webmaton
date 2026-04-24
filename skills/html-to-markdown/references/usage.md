# Usage

Two PEP 723 scripts. `uv run` manages isolated environments automatically.

## Capture (`capture_html.py`)

```bash
uv run --script scripts/capture_html.py <url> [options]
```

### Capture to JSON

Default mode and preferred output for chaining:

```bash
uv run --script scripts/capture_html.py \
  https://example.com/article \
  --output-format json
```

The JSON envelope includes:

- `html`
- `url`
- `final_url`
- `content_type`

It may also include narrow helper fields such as `title` or `rendered`.

### Capture to raw HTML

Use this mode to pipe rendered HTML directly into conversion:

```bash
uv run --script scripts/capture_html.py \
  https://example.com/article \
  --output-format html
```

### Wait controls

Use `--wait-selector` when the page is loaded only after a stable DOM hook appears:

```bash
uv run --script scripts/capture_html.py \
  https://example.com/article \
  --wait-selector article
```

Use `--wait-text` when the page has no stable selector but a clear visible string:

```bash
uv run --script scripts/capture_html.py \
  https://example.com/article \
  --wait-text "Read more"
```

Use `--timeout` to control the maximum wait time in seconds:

```bash
uv run --script scripts/capture_html.py \
  https://example.com/article \
  --wait-selector main \
  --timeout 15
```

## Convert (`markmaton_convert.py`)

```bash
uv run --script scripts/markmaton_convert.py [options]
```

### Convert to Markdown

```bash
uv run --script scripts/markmaton_convert.py \
  --html-file page.html \
  --url https://example.com/article \
  --output-format markdown
```

### Convert to JSON

```bash
uv run --script scripts/markmaton_convert.py \
  --html-file page.html \
  --url https://example.com/article \
  --output-format json
```

### Convert from capture envelope

Preferred when chaining with `capture_html.py`. Reads the JSON envelope and extracts all context fields automatically:

```bash
uv run --script scripts/capture_html.py https://example.com/article \
  | uv run --script scripts/markmaton_convert.py --from-capture --output-format json
```

CLI flags (`--url`, `--final-url`, `--content-type`) override envelope values if both are provided.

### Convert from stdin

Use when another tool already produced raw HTML:

```bash
cat page.html | uv run --script scripts/markmaton_convert.py \
  --url https://example.com/article \
  --output-format json
```

### Output modes

Use `markdown` when you only need readable Markdown.

Use `json` when you need:

- `markdown`
- `html_clean`
- `metadata`
- `links`
- `images`
- `quality`
