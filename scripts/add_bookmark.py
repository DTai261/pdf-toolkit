#!/usr/bin/env python3
"""
PDF Table of Contents Hyperlink Tool

Detects table of contents in PDF and adds hyperlinks from TOC entries to their
corresponding pages. Also adds bookmarks for all pages.
"""

import argparse
import re
import sys
from pathlib import Path

try:
    import fitz  # PyMuPDF
    PYMUPDF_AVAILABLE = True
except ImportError:
    print("Error: PyMuPDF (pymupdf) is required for this script.", file=sys.stderr)
    print("Please install: pip install pymupdf", file=sys.stderr)
    sys.exit(1)


def detect_toc_page(doc):
    """
    Detect which page contains the table of contents.
    Returns page number (0-indexed) or None.
    """
    toc_keywords = [
        'table of contents',
        'contents',
        'index',
        'table des matières',
    ]
    
    best_match = None
    best_score = 0
    
    for page_num in range(min(20, len(doc))):  # Check first 20 pages
        page = doc[page_num]
        page_text = page.get_text()
        page_text_lower = page_text.lower()
        
        score = 0
        
        # Check for TOC keywords
        for keyword in toc_keywords:
            if keyword in page_text_lower:
                score += 10
        
        # Check for TOC patterns - lines ending with page numbers
        # Pattern: text ... number at end of line
        toc_pattern_matches = len(re.findall(r'.+?\s+\d+\s*$', page_text, re.MULTILINE))
        if toc_pattern_matches > 3:  # At least 3 TOC-like entries
            score += toc_pattern_matches
        
        # Check for section numbers (e.g., "1.1", "2.3.4")
        section_pattern_matches = len(re.findall(r'\d+\.\d+', page_text))
        if section_pattern_matches > 2:
            score += section_pattern_matches
        
        if score > best_score:
            best_score = score
            best_match = page_num
    
    # If we found a good match, return it
    if best_score >= 5:
        return best_match
    
    return None


def extract_toc_entries(page):
    """
    Extract TOC entries from a page.
    Returns list of tuples: (section_num, title, page_number, bbox, full_line_text, level, page_idx)
    Handles multi-line TOC entries where section number, title, and page number may be on different lines.
    """
    toc_entries = []
    page_idx = page.number
    
    # Get text with positions
    text_dict = page.get_text("dict")
    
    # First, collect all lines with their bboxes and y-positions
    all_lines = []
    for block in text_dict.get("blocks", []):
        if block.get("type") == 0:  # Text block
            for line in block.get("lines", []):
                line_text = ""
                line_bbox_list = []
                
                for span in line.get("spans", []):
                    line_text += span.get("text", "")
                    line_bbox_list.append(span.get("bbox", []))
                
                line_text = line_text.strip()
                
                if not line_text:
                    continue
                
                # Get line bbox
                line_bbox = line.get("bbox", [])
                if not line_bbox or len(line_bbox) < 4:
                    if line_bbox_list:
                        valid_spans = [span for span in line_bbox_list if span and len(span) >= 4]
                        if valid_spans:
                            x0 = min(span[0] for span in valid_spans)
                            y0 = min(span[1] for span in valid_spans)
                            x1 = max(span[2] for span in valid_spans)
                            y1 = max(span[3] for span in valid_spans)
                            line_bbox = [x0, y0, x1, y1]
                        else:
                            line_bbox = []
                    else:
                        line_bbox = []
                
                # Get y-position for sorting/grouping
                y_pos = line_bbox[1] if line_bbox else 0
                all_lines.append((line_text, line_bbox, y_pos))
    
    # Sort lines by y-position (top to bottom)
    all_lines.sort(key=lambda x: x[2])
    
    # Skip obvious non-TOC lines
    skip_keywords = [
        'table of contents', 'contents', 'index',
        'penetration testing with kali linux',
        'pwk - copyright',
        'copyright ©',
        'all rights reserved',
    ]
    
    # Now process lines, combining multi-line entries
    i = 0
    while i < len(all_lines):
        line_text, line_bbox, y_pos = all_lines[i]
        line_lower = line_text.lower().strip()
        
        # Skip headers
        if any(keyword in line_lower for keyword in skip_keywords):
            i += 1
            continue
        
        # Skip very short lines, but keep single-digit section numbers like "1", "2"
        if len(line_text.strip()) < 1:
            i += 1
            continue
        
        # Don't skip lines that are just a single number (might be section number)
        if len(line_text.strip()) == 1 and re.match(r'^\d$', line_text.strip()):
            # This might be a section number, process it
            pass
        elif len(line_text.strip()) < 2:
            i += 1
            continue
        
        # Debug: Print first few lines
        if page_idx <= 2 and len(toc_entries) < 5:
            print(f"Debug: Processing line {i}: '{line_text[:100]}'", file=sys.stderr)
        
        # Try to match complete entry on single line first
        # Pattern: section_num + title + dots + page_number
        section_start = re.match(r'^(\d+(?:\.\d+)*)\s+', line_text)
        page_end = re.search(r'[.\s]+(\d+)\s*$', line_text)
        
        if section_start and page_end:
            # Complete entry on one line
            section_num = section_start.group(1)
            page_num = int(page_end.group(1))
            title_start = section_start.end()
            title_end = page_end.start()
            title = line_text[title_start:title_end].strip()
            title = re.sub(r'[.\s]+$', '', title).strip()
            
            title_clean = title.replace('.', '').strip()
            if (title and len(title_clean) > 0 and 
                title_clean != section_num.replace('.', '').strip() and
                page_num > 0 and page_num <= 10000):
                level = section_num.count('.') + 1
                if page_idx <= 2 and len(toc_entries) < 5:
                    print(f"Debug: Single-line match: section='{section_num}', title='{title[:50]}', page={page_num}", file=sys.stderr)
                toc_entries.append((section_num, title, page_num, line_bbox, line_text, level, page_idx))
                i += 1
                continue
        
        # Try multi-line: section number on this line, title/page on next line(s)
        # Check if this line is just a section number (like "1", "2", "2.1", "2.1.1")
        section_only_match = re.match(r'^(\d+(?:\.\d+)*)\s*$', line_text)
        if section_only_match and i + 1 < len(all_lines):
            section_num = section_only_match.group(1)
            # Look at next line for title and page number
            next_line_text, next_line_bbox, next_y = all_lines[i + 1]
            
            # Check if next line has page number at the end
            page_end = re.search(r'[.\s]+(\d+)\s*$', next_line_text)
            if page_end:
                page_num = int(page_end.group(1))
                # Title is everything before page number in next line
                title = next_line_text[:page_end.start()].strip()
                title = re.sub(r'[.\s]+$', '', title).strip()
                
                title_clean = title.replace('.', '').strip()
                if (title and len(title_clean) > 0 and 
                    page_num > 0 and page_num <= 10000):
                    level = section_num.count('.') + 1
                    combined_text = f"{section_num} {title} {page_num}"
                    # Use bbox from title line (next line)
                    if page_idx <= 2 and len(toc_entries) < 5:
                        print(f"Debug: Multi-line match: section='{section_num}', title='{title[:50]}', page={page_num}", file=sys.stderr)
                    toc_entries.append((section_num, title, page_num, next_line_bbox, combined_text, level, page_idx))
                    i += 2  # Skip both lines
                    continue
            # Also check if next line is just title (no page number), then check line after that
            elif i + 2 < len(all_lines):
                # Maybe: "1" -> "Copyright" -> "15" (three lines)
                # Or: "1" -> "Copyright ................ 15" (two lines, but we already checked)
                # Check if next line is title and line after has page number
                third_line_text, third_line_bbox, third_y = all_lines[i + 2]
                page_match = re.search(r'(\d+)\s*$', third_line_text)
                if page_match and not re.match(r'^\d', next_line_text):
                    # Next line is title, third line has page number
                    title = next_line_text.strip()
                    title = re.sub(r'[.\s]+$', '', title).strip()
                    page_num = int(page_match.group(1))
                    
                    if (title and len(title.replace('.', '').strip()) > 0 and 
                        page_num > 0 and page_num <= 10000):
                        level = section_num.count('.') + 1
                        combined_text = f"{section_num} {title} {page_num}"
                        if page_idx <= 2 and len(toc_entries) < 5:
                            print(f"Debug: Multi-line match (3 lines): section='{section_num}', title='{title[:50]}', page={page_num}", file=sys.stderr)
                        toc_entries.append((section_num, title, page_num, next_line_bbox, combined_text, level, page_idx))
                        i += 3  # Skip all three lines
                        continue
        
        # Try: section number + partial title on this line, page number on next
        section_start = re.match(r'^(\d+(?:\.\d+)*)\s+(.+)$', line_text)
        if section_start and i + 1 < len(all_lines):
            section_num = section_start.group(1)
            partial_title = section_start.group(2).strip()
            next_line_text, next_line_bbox, next_y = all_lines[i + 1]
            
            # Check if next line is just a page number or has page number at end
            page_match = re.search(r'(\d+)\s*$', next_line_text)
            if page_match:
                page_num = int(page_match.group(1))
                # Combine titles
                title = f"{partial_title} {next_line_text[:page_match.start()].strip()}".strip()
                title = re.sub(r'[.\s]+$', '', title).strip()
                
                title_clean = title.replace('.', '').strip()
                if (title and len(title_clean) > 0 and 
                    title_clean != section_num.replace('.', '').strip() and
                    page_num > 0 and page_num <= 10000):
                    level = section_num.count('.') + 1
                    combined_text = f"{section_num} {title} {page_num}"
                    if page_idx <= 2 and len(toc_entries) < 5:
                        print(f"Debug: Multi-line match (split): section='{section_num}', title='{title[:50]}', page={page_num}", file=sys.stderr)
                    toc_entries.append((section_num, title, page_num, next_line_bbox, combined_text, level, page_idx))
                    i += 2
                    continue
        
        # Try: title on this line with page number, but check if previous line was a section number
        # This handles cases like: "1" (previous line) -> "Copyright ................ 15" (this line)
        if i > 0:
            prev_line_text, prev_line_bbox, prev_y = all_lines[i - 1]
            prev_section_match = re.match(r'^(\d+(?:\.\d+)*)\s*$', prev_line_text)
            if prev_section_match:
                # Previous line was a section number, this line might be title + page
                section_num = prev_section_match.group(1)
                page_end = re.search(r'[.\s]+(\d+)\s*$', line_text)
                if page_end:
                    page_num = int(page_end.group(1))
                    title = line_text[:page_end.start()].strip()
                    title = re.sub(r'[.\s]+$', '', title).strip()
                    
                    title_clean = title.replace('.', '').strip()
                    if (title and len(title_clean) > 0 and 
                        page_num > 0 and page_num <= 10000):
                        level = section_num.count('.') + 1
                        combined_text = f"{section_num} {title} {page_num}"
                        if page_idx <= 2 and len(toc_entries) < 5:
                            print(f"Debug: Previous-line section match: section='{section_num}', title='{title[:50]}', page={page_num}", file=sys.stderr)
                        toc_entries.append((section_num, title, page_num, line_bbox, combined_text, level, page_idx))
                        i += 1
                        continue
                # Also check if page number is on the next line
                elif i + 1 < len(all_lines):
                    next_line_text, next_line_bbox, next_y = all_lines[i + 1]
                    page_match = re.search(r'(\d+)\s*$', next_line_text)
                    if page_match and len(next_line_text.strip()) <= 3:  # Next line is likely just a page number
                        page_num = int(page_match.group(1))
                        title = line_text.strip()
                        title = re.sub(r'[.\s]+$', '', title).strip()
                        
                        if (title and len(title.replace('.', '').strip()) > 0 and 
                            page_num > 0 and page_num <= 10000):
                            level = section_num.count('.') + 1
                            combined_text = f"{section_num} {title} {page_num}"
                            if page_idx <= 2 and len(toc_entries) < 5:
                                print(f"Debug: Previous-line section + next-line page: section='{section_num}', title='{title[:50]}', page={page_num}", file=sys.stderr)
                            toc_entries.append((section_num, title, page_num, line_bbox, combined_text, level, page_idx))
                            i += 2  # Skip this line and next line
                            continue
        
        # Try: title on this line, page number on next (no section number visible)
        # This is a fallback for entries without section numbers
        page_end = re.search(r'[.\s]+(\d+)\s*$', line_text)
        if not page_end and i + 1 < len(all_lines):
            next_line_text, next_line_bbox, next_y = all_lines[i + 1]
            page_match = re.search(r'(\d+)\s*$', next_line_text)
            if page_match and not re.match(r'^\d', line_text):
                # This might be a title without section number
                title = line_text.strip()
                title = re.sub(r'[.\s]+$', '', title).strip()
                page_num = int(page_match.group(1))
                
                if (len(title) > 3 and page_num > 0 and page_num <= 10000 and
                    not re.match(r'^\d+(?:\.\d+)*\s*$', title)):
                    # Only add if we really can't find a section number
                    # Skip for now - we want entries with section numbers
                    pass
        
        i += 1
    
    return toc_entries


def find_text_on_page(page, search_text, fuzzy=True):
    """
    Find text on a page and return its bounding box.
    Returns list of Rect objects.
    """
    try:
        # Try exact search first
        rects = page.search_for(search_text)
        if rects:
            return rects
        
        # Try fuzzy search if enabled
        if fuzzy:
            # Try with variations
            # Remove special characters
            clean_text = re.sub(r'[^\w\s]', '', search_text)
            if clean_text != search_text:
                rects = page.search_for(clean_text)
                if rects:
                    return rects
            
            # Try first few words
            words = search_text.split()
            if len(words) > 1:
                first_words = ' '.join(words[:3])
                rects = page.search_for(first_words)
                if rects:
                    return rects
        
        return []
    except:
        return []


def add_toc_hyperlinks(doc, toc_entries, toc_page_idx):
    """
    Add hyperlinks from TOC entries to their target pages.
    TEMPORARILY DISABLED for debugging.
    """
    # Temporarily disabled
    return 0


def add_toc_bookmarks(doc, toc_entries):
    """
    Add bookmarks from TOC entries.
    Filters out page headers and other non-TOC content.
    Maintains proper hierarchy based on section numbers.
    """
    try:
        # Build new TOC list from TOC entries
        new_toc = []
        
        # Common page headers/footers to filter out
        skip_patterns = [
            'penetration testing with kali linux',
            'pwk - copyright',
            'copyright',
            'table of contents',
            'contents',
        ]
        
        # Sort entries by page number first, then by section number to maintain proper order
        def sort_key(entry):
            if len(entry) >= 3:
                page_num = entry[2]
                section_num = entry[0] if len(entry) >= 1 else ""
                # Convert section number to tuple for proper sorting (e.g., "2.1.3" -> (2, 1, 3))
                if section_num:
                    try:
                        section_parts = tuple(int(x) for x in section_num.split('.'))
                        return (page_num, section_parts)
                    except:
                        return (page_num, (0,))
                return (page_num, (0,))
            return (0, (0,))
        
        sorted_entries = sorted(toc_entries, key=sort_key)
        
        # Debug: Check what we're getting
        print(f"Total entries to process: {len(sorted_entries)}", file=sys.stderr)
        entries_with_section = sum(1 for e in sorted_entries if len(e) >= 1 and e[0] and e[0].strip())
        entries_without_section = len(sorted_entries) - entries_with_section
        print(f"Entries with section numbers: {entries_with_section}, without: {entries_without_section}", file=sys.stderr)
        
        if len(sorted_entries) > 0:
            print(f"First 5 entries:", file=sys.stderr)
            for i, entry in enumerate(sorted_entries[:5]):
                if len(entry) >= 6:
                    section = entry[0] if entry[0] else "(empty)"
                    title_preview = entry[1][:60] if entry[1] else "(empty)"
                    print(f"  Entry {i}: section='{section}', title='{title_preview}...', page={entry[2]}, level={entry[5]}", file=sys.stderr)
        
        for entry in sorted_entries:
            # Handle both old format (6 items) and new format (7 items)
            if len(entry) >= 6:
                section_num = entry[0]
                title = entry[1]
                page_num = entry[2]
                level = entry[5]
            else:
                continue
            
            # Skip entries with empty or invalid titles
            if not title or not isinstance(title, str):
                continue
            
            title = title.strip()
            
            # Skip if title is just whitespace or very short
            if len(title) < 3:
                continue
            
            # Skip if title is just a section number (like "10.1" without actual title)
            if title == section_num or (section_num and title.replace('.', '').strip() == section_num.replace('.', '').strip()):
                continue
            
            # Skip if title matches header patterns (but be more specific)
            title_lower = title.lower()
            # Only skip if it's clearly a header/footer, not a TOC entry
            # For example, "1 Copyright" should NOT be skipped, but "Copyright © 2023" should be
            if any(pattern in title_lower for pattern in skip_patterns):
                # Additional check: if it has a section number and page number, it's likely a TOC entry
                # Don't skip entries that have section numbers (they're real TOC entries)
                if not section_num or not section_num.strip():
                    # Only skip if it doesn't have a section number (likely a header)
                    continue
            
            # Skip entries that are just numbers (likely page numbers or section numbers only)
            if re.match(r'^\d+(?:\.\d+)*\s*$', title):
                continue
            
            # Ensure we have a valid page number
            if page_num <= 0 or page_num > len(doc):
                continue
            
            # Calculate level properly based on section number depth
            if section_num and section_num.strip():
                # Count dots to determine hierarchy level (1.2.3 = level 3)
                # "1" = level 1, "2.1" = level 2, "2.1.1" = level 3
                level = section_num.count('.') + 1
            else:
                level = 1
            
            # Create bookmark title - ALWAYS include section number if available
            title_clean = title.strip()
            section_stripped = section_num.strip() if section_num else ""
            
            # CRITICAL: If we have a section number, it MUST appear in the bookmark title
            if section_stripped:
                # Remove section number from title if it's already there (to avoid duplication)
                title_without_section = title_clean
                
                # Check various formats where section number might already be in title
                if title_clean.startswith(section_stripped + " "):
                    title_without_section = title_clean[len(section_stripped) + 1:].strip()
                elif title_clean.startswith(section_stripped + "."):
                    title_without_section = title_clean[len(section_stripped) + 1:].strip()
                elif title_clean == section_stripped:
                    # Title is just the section number, skip this entry
                    continue
                
                # Always format as "section_num title" - ensure section number is included
                if title_without_section:
                    bookmark_title = f"{section_stripped} {title_without_section}".strip()
                else:
                    # Title was empty after removing section number, skip
                    continue
            else:
                # No section number - log this for debugging
                print(f"Warning: Entry without section number: '{title_clean}' (page {page_num})", file=sys.stderr)
                # Use title as is, but this shouldn't happen for proper TOC entries
                bookmark_title = title_clean
            
            # Debug: Print what we're adding to TOC (first 5 only)
            if len(new_toc) < 5:
                print(f"Adding bookmark: level={level}, title='{bookmark_title}', page={page_num}", file=sys.stderr)
            
            # Add to TOC (level, title, page) - page numbers are 1-indexed in TOC
            # Format: [level, title, page] where level is 1-indexed hierarchy depth
            new_toc.append([level, bookmark_title, page_num])
        
        # Set the new TOC
        if new_toc:
            # PyMuPDF requires the first bookmark to be level 1
            # If the first entry is not level 1, we need to adjust or skip it
            if new_toc and new_toc[0][0] != 1:
                print(f"Warning: First bookmark is level {new_toc[0][0]}, but must be level 1. Adjusting...", file=sys.stderr)
                # Try to find a level 1 entry to put first, or adjust the first one
                level_1_found = False
                for j, entry in enumerate(new_toc):
                    if entry[0] == 1:
                        # Move this level 1 entry to the front
                        new_toc.insert(0, new_toc.pop(j))
                        level_1_found = True
                        break
                
                if not level_1_found:
                    # No level 1 entry found, we need to create one or adjust
                    # For now, let's set the first entry to level 1 (this might not be ideal but will work)
                    print(f"Warning: No level 1 entry found. Setting first entry to level 1.", file=sys.stderr)
                    new_toc[0][0] = 1
            
            doc.set_toc(new_toc)
            return len(new_toc)
        
        return 0
    except Exception as e:
        print(f"Warning: Could not add bookmarks: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 0


def main():
    parser = argparse.ArgumentParser(
        description='Add hyperlinks to table of contents and bookmarks to all pages',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s -i document.pdf -o document_with_links.pdf
  %(prog)s -i book.pdf -o book_linked.pdf
  %(prog)s -i book.pdf -o book_linked.pdf -ir 3,14
  %(prog)s -i book.pdf -o book_linked.pdf --index-range 3-14
        """
    )
    
    parser.add_argument(
        '-i', '--input',
        required=True,
        help='Input PDF file path'
    )
    
    parser.add_argument(
        '-o', '--output',
        required=True,
        help='Output PDF file path'
    )
    
    parser.add_argument(
        '-ir', '--index-range',
        type=str,
        default=None,
        help='Specify TOC page range as "start,end" or "start-end" (1-indexed). Example: -ir 3,14 or -ir 3-14'
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
    
    # Validate output path
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    print(f"Processing PDF: {input_path}", file=sys.stderr)
    print(f"Output will be saved to: {output_path}", file=sys.stderr)
    
    try:
        # Open PDF
        doc = fitz.open(input_path)
        
        if len(doc) == 0:
            print("Error: PDF has no pages", file=sys.stderr)
            doc.close()
            sys.exit(1)
        
        print(f"PDF has {len(doc)} pages", file=sys.stderr)
        
        # Parse index range if provided
        toc_start_idx = None
        toc_end_idx = None
        
        if args.index_range:
            # Parse range: support both "3,14" and "3-14" formats
            range_str = args.index_range.strip()
            if ',' in range_str:
                parts = range_str.split(',')
            elif '-' in range_str:
                parts = range_str.split('-')
            else:
                print(f"Error: Invalid index range format. Use 'start,end' or 'start-end' (e.g., '3,14' or '3-14')", file=sys.stderr)
                doc.close()
                sys.exit(1)
            
            if len(parts) != 2:
                print(f"Error: Invalid index range format. Use 'start,end' or 'start-end' (e.g., '3,14' or '3-14')", file=sys.stderr)
                doc.close()
                sys.exit(1)
            
            try:
                start_page = int(parts[0].strip())
                end_page = int(parts[1].strip())
                
                # Convert from 1-indexed to 0-indexed
                toc_start_idx = start_page - 1
                toc_end_idx = end_page - 1
                
                # Validate range
                if toc_start_idx < 0 or toc_end_idx >= len(doc):
                    print(f"Error: Index range {start_page}-{end_page} is out of bounds (PDF has {len(doc)} pages)", file=sys.stderr)
                    doc.close()
                    sys.exit(1)
                
                if toc_start_idx > toc_end_idx:
                    print(f"Error: Start page ({start_page}) must be <= end page ({end_page})", file=sys.stderr)
                    doc.close()
                    sys.exit(1)
                
                print(f"Using specified TOC range: pages {start_page} to {end_page}", file=sys.stderr)
            except ValueError:
                print(f"Error: Invalid page numbers in index range. Use integers (e.g., '3,14')", file=sys.stderr)
                doc.close()
                sys.exit(1)
        
        # Detect TOC page(s) - TOC might span multiple pages
        if toc_start_idx is None:
            # Auto-detect TOC
            toc_page_idx = detect_toc_page(doc)
            if toc_page_idx is None:
                print("Warning: Could not detect table of contents page. Trying first few pages...", file=sys.stderr)
                # Try first 3 pages
                toc_page_idx = 0
            
            print(f"Processing table of contents starting from page {toc_page_idx + 1}...", file=sys.stderr)
            
            # Extract TOC entries from multiple pages (TOC often spans 2-5 pages)
            toc_entries = []
            toc_pages = []
            max_toc_pages = 10  # Check up to 10 pages for TOC
            
            for page_offset in range(max_toc_pages):
                check_page_idx = toc_page_idx + page_offset
                if check_page_idx >= len(doc):
                    break
                
                page = doc[check_page_idx]
                page_text = page.get_text()
                
                # Check if this page still has TOC content
                # TOC pages typically have entries ending with page numbers
                toc_like_entries = len(re.findall(r'.+?\s+\d+\s*$', page_text, re.MULTILINE))
                
                if toc_like_entries < 2 and page_offset > 0:
                    # Not enough TOC-like entries, probably end of TOC
                    break
                
                page_entries = extract_toc_entries(page)
                if page_entries:
                    toc_entries.extend(page_entries)
                    toc_pages.append(check_page_idx)
                    print(f"Found {len(page_entries)} TOC entries on page {check_page_idx + 1}", file=sys.stderr)
                elif page_offset == 0:
                    # First page should have entries, if not try next page
                    continue
                else:
                    # No more entries found
                    break
        else:
            # Use specified range
            print(f"Processing table of contents from pages {toc_start_idx + 1} to {toc_end_idx + 1}...", file=sys.stderr)
            toc_entries = []
            toc_pages = []
            
            for check_page_idx in range(toc_start_idx, toc_end_idx + 1):
                if check_page_idx >= len(doc):
                    break
                
                page = doc[check_page_idx]
                page_entries = extract_toc_entries(page)
                if page_entries:
                    toc_entries.extend(page_entries)
                    toc_pages.append(check_page_idx)
                    print(f"Found {len(page_entries)} TOC entries on page {check_page_idx + 1}", file=sys.stderr)
        
        if not toc_entries:
            print("Error: Could not extract table of contents entries.", file=sys.stderr)
            print("The PDF may not have a table of contents, or it's in an unsupported format.", file=sys.stderr)
            doc.close()
            sys.exit(1)
        
        print(f"Found {len(toc_entries)} TOC entries", file=sys.stderr)
        if len(toc_entries) <= 10:
            for section_num, title, page_num, _, _, level in toc_entries:
                if section_num:
                    print(f"  - {section_num} {title} -> Page {page_num} (level {level})", file=sys.stderr)
        
        # Add hyperlinks (TEMPORARILY DISABLED)
        print("Adding hyperlinks...", file=sys.stderr)
        links_added = 0
        # Temporarily disabled for debugging
        # for toc_page_num in toc_pages:
        #     if toc_page_num in entries_by_page:
        #         page_entries = entries_by_page[toc_page_num]
        #         page_links = add_toc_hyperlinks(doc, page_entries, toc_page_num)
        #         links_added += page_links
        
        print(f"Added {links_added} hyperlinks", file=sys.stderr)
        
        # Add bookmarks from table of contents
        print("Adding bookmarks from table of contents...", file=sys.stderr)
        bookmarks_added = add_toc_bookmarks(doc, toc_entries)
        print(f"Added {bookmarks_added} bookmarks", file=sys.stderr)
        
        # Save the modified PDF
        doc.save(output_path)
        doc.close()
        
        print(f"Successfully processed PDF. Output saved to: {output_path}", file=sys.stderr)
        
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
