# PDF Toolkit

A collection of scripts and tools for working with PDF files.

## Tools

| Tool | Description |
|------|-------------|
| [remove_watermark.py](scripts/remove_watermark.py) | Removes watermarks from PDF files with auto-detection or manual specification. Supports `-i/--input`, `-rs/--remove-string`, and `-o/--output` options. |
| [add_bookmark.py](scripts/add_bookmark.py) | Detects table of contents in PDF and adds clickable hyperlinks from TOC entries to their corresponding pages. Also adds bookmarks for all pages. Supports `-i/--input`, `-o/--output` and `-ir/--index-range` options. |
| [extract_pages.py](scripts/extract_pages.py) | Extracts a range of pages from a PDF file. Supports `-i/--input`, `-o/--output` (optional), and `-pr/--page-range` options. Default output: `<input>_<start>-<end>.pdf`. |

## Usage

Each tool is a standalone script. Refer to the individual tool's documentation or help text for usage instructions.

## Contributing

When adding a new tool:
1. Create the script in the appropriate directory
2. Add an entry to the table above with:
   - Tool name
   - Short description
   - Clickable link to the script file

## License

See [LICENSE](LICENSE) file for details.
