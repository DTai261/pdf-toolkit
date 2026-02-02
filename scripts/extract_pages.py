#!/usr/bin/env python3
"""
PDF Page Range Extractor

Extracts a range of pages from a PDF file and saves them to a new PDF.
"""

import argparse
import sys
from pathlib import Path

try:
    import fitz  # PyMuPDF
    PYMUPDF_AVAILABLE = True
except ImportError:
    print("Error: PyMuPDF (pymupdf) is required for this script.", file=sys.stderr)
    print("Please install: pip install pymupdf", file=sys.stderr)
    sys.exit(1)


def extract_pages(input_path, output_path, start_page, end_page):
    """
    Extract pages from start_page to end_page (1-indexed, inclusive) from input PDF.
    """
    try:
        # Open input PDF
        doc = fitz.open(input_path)
        
        if len(doc) == 0:
            print("Error: Input PDF has no pages", file=sys.stderr)
            doc.close()
            sys.exit(1)
        
        # Validate page range (convert from 1-indexed to 0-indexed)
        start_idx = start_page - 1
        end_idx = end_page - 1
        
        if start_idx < 0 or end_idx >= len(doc):
            print(f"Error: Page range {start_page}-{end_page} is out of bounds (PDF has {len(doc)} pages)", file=sys.stderr)
            doc.close()
            sys.exit(1)
        
        if start_idx > end_idx:
            print(f"Error: Start page ({start_page}) must be <= end page ({end_page})", file=sys.stderr)
            doc.close()
            sys.exit(1)
        
        # Extract pages (end_idx is inclusive in PyMuPDF)
        print(f"Extracting pages {start_page} to {end_page} (inclusive)...", file=sys.stderr)
        new_doc = fitz.open()
        new_doc.insert_pdf(doc, from_page=start_idx, to_page=end_idx)
        
        # Save output PDF
        new_doc.save(output_path)
        new_doc.close()
        doc.close()
        
        print(f"Successfully extracted {end_page - start_page + 1} pages. Output saved to: {output_path}", file=sys.stderr)
        
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description='Extract a range of pages from a PDF file',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s -i document.pdf -pr 10,20
  %(prog)s -i document.pdf -pr 10-20 -o output.pdf
  %(prog)s -i book.pdf --page-range 286,314
        """
    )
    
    parser.add_argument(
        '-i', '--input',
        required=True,
        help='Input PDF file path'
    )
    
    parser.add_argument(
        '-o', '--output',
        type=str,
        default=None,
        help='Output PDF file path (default: <input>_<start>-<end>.pdf)'
    )
    
    parser.add_argument(
        '-pr', '--page-range',
        required=True,
        help='Page range as "start,end" or "start-end" (1-indexed, inclusive). Example: -pr 286,314 or -pr 286-314'
    )
    
    args = parser.parse_args()
    
    # Validate input file
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: Input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)
    
    if not input_path.suffix.lower() == '.pdf':
        print(f"Error: Input file must be a PDF: {input_path}", file=sys.stderr)
        sys.exit(1)
    
    # Parse page range
    range_str = args.page_range.strip()
    if ',' in range_str:
        parts = range_str.split(',')
    elif '-' in range_str:
        parts = range_str.split('-')
    else:
        print(f"Error: Invalid page range format. Use 'start,end' or 'start-end' (e.g., '286,314' or '286-314')", file=sys.stderr)
        sys.exit(1)
    
    if len(parts) != 2:
        print(f"Error: Invalid page range format. Use 'start,end' or 'start-end' (e.g., '286,314' or '286-314')", file=sys.stderr)
        sys.exit(1)
    
    try:
        start_page = int(parts[0].strip())
        end_page = int(parts[1].strip())
        
        if start_page < 1:
            print(f"Error: Start page must be >= 1", file=sys.stderr)
            sys.exit(1)
        
        if end_page < start_page:
            print(f"Error: End page ({end_page}) must be >= start page ({start_page})", file=sys.stderr)
            sys.exit(1)
        
    except ValueError:
        print(f"Error: Invalid page numbers in range. Use integers (e.g., '286,314')", file=sys.stderr)
        sys.exit(1)
    
    # Determine output path
    if args.output:
        output_path = Path(args.output)
    else:
        # Default: <input>_<start>-<end>.pdf
        input_stem = input_path.stem
        output_path = input_path.parent / f"{input_stem}_{start_page}-{end_page}.pdf"
    
    # Create output directory if needed
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    print(f"Processing PDF: {input_path}", file=sys.stderr)
    print(f"Output will be saved to: {output_path}", file=sys.stderr)
    
    # Extract pages
    extract_pages(input_path, output_path, start_page, end_page)


if __name__ == '__main__':
    main()
