# uart_govee
Python uart receiver application using govee API to control bedroom lights. I will be filtering for just H6006 model lights since those are the only ones I want to toggle.

## Configuration / .env

The script reads configuration from a `.env` file in the repository root. Copy `.env.example` to `.env` and fill values.

- `GOVEE_API_KEY` — your Govee developer API key (required for API discovery and control)
- `GOVEE_DEVICES` — optional. If present, the script parses devices from this string instead of calling the API. Format:
	`aa:bb:cc:dd:ee:ff:MODEL;11:22:33:44:55:66:MODEL`
- `COOLDOWN_MS` — milliseconds to wait between actions to avoid duplicates (default in code: 800)
- `ALLOWED_MODEL` — (optional) model code to filter devices by (default: `H6006`). Leave empty to disable model filtering.

See `.env.example` for a ready-to-copy example.
