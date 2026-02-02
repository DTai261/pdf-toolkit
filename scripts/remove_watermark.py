#!/usr/bin/env python3
"""
PDF Watermark Removal Tool

Removes watermarks from PDF files. Can auto-detect watermarks or remove
a specific string pattern.
"""

import argparse
import os
import sys
from pathlib import Path

# Try PyMuPDF first (better for watermark removal), fallback to pypdf/pdfplumber
try:
    import fitz  # PyMuPDF
    PYMUPDF_AVAILABLE = True
except ImportError:
    PYMUPDF_AVAILABLE = False
    try:
        from pypdf import PdfReader, PdfWriter
        import pdfplumber
    except ImportError:
        print("Error: Required packages not installed.", file=sys.stderr)
        print("Please install one of:", file=sys.stderr)
        print("  pip install pymupdf  (recommended)", file=sys.stderr)
        print("  OR", file=sys.stderr)
        print("  pip install pypdf pdfplumber", file=sys.stderr)
        sys.exit(1)


def detect_watermark_text(pdf_path, sample_pages=3):
    """
    Auto-detect watermark text by finding text that appears on multiple pages.
    Returns the most common watermark text or None.
    """
    if PYMUPDF_AVAILABLE:
        try:
            doc = fitz.open(pdf_path)
            if len(doc) == 0:
                doc.close()
                return None
            
            pages_to_check = min(sample_pages, len(doc))
            text_frequency = {}
            
            for page_num in range(pages_to_check):
                page = doc[page_num]
                text_dict = page.get_text("dict")
                
                # Extract text blocks
                for block in text_dict.get("blocks", []):
                    if "lines" in block:
                        for line in block["lines"]:
                            line_text = ""
                            for span in line.get("spans", []):
                                line_text += span.get("text", "")
                            line_text = line_text.strip()
                            if len(line_text) > 3:
                                text_frequency[line_text] = text_frequency.get(line_text, 0) + 1
            
            doc.close()
            
            if text_frequency:
                most_common = max(text_frequency.items(), key=lambda x: x[1])
                if most_common[1] >= pages_to_check * 0.7:
                    return most_common[0]
            
            return None
        except Exception as e:
            print(f"Warning: Could not auto-detect watermark: {e}", file=sys.stderr)
            return None
    else:
        try:
            import pdfplumber
            with pdfplumber.open(pdf_path) as pdf:
                if len(pdf.pages) == 0:
                    return None
                
                pages_to_check = min(sample_pages, len(pdf.pages))
                common_patterns = {}
                
                for i in range(pages_to_check):
                    page = pdf.pages[i]
                    text = page.extract_text()
                    if text:
                        lines = text.split('\n')
                        for line in lines:
                            line = line.strip()
                            if len(line) > 3:
                                common_patterns[line] = common_patterns.get(line, 0) + 1
                
                if common_patterns:
                    most_common = max(common_patterns.items(), key=lambda x: x[1])
                    if most_common[1] >= pages_to_check * 0.7:
                        return most_common[0]
                
                return None
        except Exception as e:
            print(f"Warning: Could not auto-detect watermark: {e}", file=sys.stderr)
            return None


def process_form_xobject(doc, xobj_xref, watermark_lowers, page_num):
    """Process a form XObject to remove watermark text"""
    import re
    
    try:
        # Get XObject stream using xref
        xobj_stream_bytes = doc.xref_stream(xobj_xref)
        if not xobj_stream_bytes:
            return False
        
        # Decode stream
        try:
            xobj_stream_text = xobj_stream_bytes.decode('utf-8', errors='ignore')
        except:
            try:
                xobj_stream_text = xobj_stream_bytes.decode('latin-1', errors='ignore')
            except:
                return False
        
        original_xobj_stream = xobj_stream_text
        new_xobj_stream = xobj_stream_text
        
        # Check if watermark is in this XObject
        xobj_stream_lower = xobj_stream_text.lower()
        has_watermark = any(wm_lower in xobj_stream_lower for wm_lower in watermark_lowers)
        
        if not has_watermark:
            return False
        
        if page_num < 3:
            print(f"Debug: Page {page_num + 1} - Found watermark in form XObject (xref {xobj_xref})", file=sys.stderr)
        
        # Extract text from stream
        def extract_all_text_from_stream(stream):
            all_text = []
            i = 0
            while i < len(stream):
                if stream[i] == '(':
                    j = i + 1
                    content = []
                    while j < len(stream):
                        if stream[j] == '\\' and j + 1 < len(stream):
                            esc_char = stream[j+1]
                            if esc_char in '()nrtbf':
                                content.append(esc_char)
                            j += 2
                        elif stream[j] == ')':
                            all_text.append(''.join(content))
                            i = j + 1
                            break
                        else:
                            content.append(stream[j])
                            j += 1
                    else:
                        i += 1
                else:
                    i += 1
            
            hex_matches = re.findall(r'<([0-9A-Fa-f]+)>', stream)
            for hex_str in hex_matches:
                try:
                    if len(hex_str) % 2 == 0:
                        try:
                            decoded = bytes.fromhex(hex_str).decode('utf-8', errors='ignore')
                        except:
                            decoded = bytes.fromhex(hex_str).decode('latin-1', errors='ignore')
                        all_text.append(decoded)
                except:
                    pass
            
            return ' '.join(all_text).lower()
        
        # Remove text objects containing watermark
        text_object_pattern = r'BT(.*?)ET'
        def should_remove_text_object(match):
            block = match.group(1)
            extracted = extract_all_text_from_stream(block)
            return any(wm_lower in extracted for wm_lower in watermark_lowers)
        
        new_xobj_stream = re.sub(text_object_pattern,
                               lambda m: '' if should_remove_text_object(m) else m.group(0),
                               new_xobj_stream, flags=re.DOTALL)
        
        # Remove inline text operators
        def should_remove_inline(match):
            text_str = match.group(1)
            text_str = text_str.replace('\\\\(', '(').replace('\\\\)', ')')
            text_str = text_str.replace('\\\\', '\\')
            return any(wm_lower in text_str.lower() for wm_lower in watermark_lowers)
        
        new_xobj_stream = re.sub(r'\(([^)]*)\)\s+Tj\b',
                               lambda m: '' if should_remove_inline(m) else m.group(0),
                               new_xobj_stream)
        
        def should_remove_tj_array(match):
            array_content = match.group(1)
            extracted = extract_all_text_from_stream(array_content)
            return any(wm_lower in extracted for wm_lower in watermark_lowers)
        
        new_xobj_stream = re.sub(r'\[([^\]]*)\]\s+TJ\b',
                               lambda m: '' if should_remove_tj_array(m) else m.group(0),
                               new_xobj_stream)
        
        new_xobj_stream = re.sub(r'\(([^)]*)\)\s+\'\b',
                               lambda m: '' if should_remove_inline(m) else m.group(0),
                               new_xobj_stream)
        new_xobj_stream = re.sub(r'\(([^)]*)\)\s+"\b',
                               lambda m: '' if should_remove_inline(m) else m.group(0),
                               new_xobj_stream)
        
        # Update XObject stream if modified
        if new_xobj_stream != original_xobj_stream:
            try:
                new_stream_bytes = new_xobj_stream.encode('latin-1', errors='ignore')
                doc.update_stream(xobj_xref, new_stream_bytes, compress=False)
                if page_num < 3:
                    print(f"Debug: Page {page_num + 1} - Updated form XObject (xref {xobj_xref})", file=sys.stderr)
                return True
            except Exception as e:
                try:
                    doc.update_stream(xobj_xref, new_stream_bytes, compress=True)
                    if page_num < 3:
                        print(f"Debug: Page {page_num + 1} - Updated form XObject (xref {xobj_xref}, compressed)", file=sys.stderr)
                    return True
                except Exception as e2:
                    if page_num < 3:
                        print(f"Debug: Page {page_num + 1} - Failed to update XObject (xref {xobj_xref}): {e2}", file=sys.stderr)
                    return False
        
        return False
    except Exception as e:
        if page_num < 3:
            print(f"Debug: Page {page_num + 1} - Error processing XObject: {e}", file=sys.stderr)
        return False


def remove_watermark_pymupdf(pdf_path, watermark_strings, output_path):
    """
    Remove watermark using PyMuPDF (fitz) by manipulating content stream.
    watermark_strings: list of watermark strings to remove, or None
    """
    import re
    
    try:
        doc = fitz.open(pdf_path)
        watermark_list = watermark_strings if watermark_strings else []
        watermark_lowers = [w.lower() for w in watermark_list] if watermark_list else []
        
        pages_processed = 0
        for page_num in range(len(doc)):
            page = doc[page_num]
            
            if not watermark_list:
                continue
            
            # First, check if watermark exists on this page
            page_text = page.get_text().lower()
            has_watermark = any(wm_lower in page_text for wm_lower in watermark_lowers)
            if not has_watermark:
                continue
            
            pages_processed += 1
            if pages_processed % 100 == 0:
                print(f"Processing page {page_num + 1}...", file=sys.stderr)
            
            # Remove annotations containing watermark
            annots_to_delete = []
            for annot in page.annots():
                try:
                    annot_info = annot.info
                    content = annot_info.get("content", "")
                    title = annot_info.get("title", "")
                    content_lower = content.lower()
                    title_lower = title.lower()
                    if any(wm_lower in content_lower or wm_lower in title_lower for wm_lower in watermark_lowers):
                        annots_to_delete.append(annot)
                except:
                    pass
            
            for annot in annots_to_delete:
                try:
                    page.delete_annot(annot)
                except:
                    pass
            
            # Get all text instances using search_for for each watermark string
            watermark_rects = []
            for watermark_text in watermark_list:
                try:
                    rects = page.search_for(watermark_text)
                    watermark_rects.extend(rects)
                except:
                    pass
            
            # Get text blocks to identify watermark locations
            text_dict = page.get_text("dict")
            found_watermarks = []
            
            # Find all text spans containing watermark
            for block in text_dict.get("blocks", []):
                if block.get("type") == 0:  # Text block
                    for line in block.get("lines", []):
                        for span in line.get("spans", []):
                            span_text = span.get("text", "")
                            span_text_lower = span_text.lower()
                            for wm_lower in watermark_lowers:
                                if wm_lower in span_text_lower:
                                    found_watermarks.append(span_text)
                                    break
            
            if found_watermarks and page_num < 5:  # Only print for first few pages
                print(f"Found watermark text on page {page_num + 1}: {found_watermarks[:3]}...", file=sys.stderr)
            
            # Remove watermark using text search and direct content stream manipulation
            try:
                # Clean contents first to normalize
                page.clean_contents()
                
                # Get all text instances of watermark using search_for
                all_watermark_instances = []
                for watermark_text in watermark_list:
                    try:
                        instances = page.search_for(watermark_text, flags=fitz.TEXT_DEHYPHENATE)
                        all_watermark_instances.extend(instances)
                    except:
                        pass
                
                if not all_watermark_instances:
                    continue
                
                # Get content stream
                try:
                    stream_bytes = page.read_contents()
                    if not stream_bytes:
                        continue
                except:
                    continue
                
                # Decode content stream
                try:
                    stream_text = stream_bytes.decode('utf-8', errors='ignore')
                except:
                    try:
                        stream_text = stream_bytes.decode('latin-1', errors='ignore')
                    except:
                        continue
                
                original_stream = stream_text
                new_stream_text = stream_text
                
                # Verify watermark text exists in stream (for debugging)
                if page_num < 3:
                    stream_text_lower = stream_text.lower()
                    found_in_stream = any(wm_lower in stream_text_lower for wm_lower in watermark_lowers)
                    if found_in_stream:
                        print(f"Debug: Page {page_num + 1} - Watermark found in content stream", file=sys.stderr)
                    else:
                        print(f"Debug: Page {page_num + 1} - Watermark NOT found in content stream (checking form XObjects)", file=sys.stderr)
                
                # Handle form XObjects - watermark is likely here
                # Process all form XObjects referenced by this page
                try:
                    # Get page's XObject resources
                    xobjects_found = False
                    try:
                        # Access page dictionary to get resources
                        page_dict = page.get_contents()
                        
                        # Try to get XObjects from page
                        # Method: Iterate through all XObjects in document and check if they're used by this page
                        # Get all XObjects from document
                        for xref_num in range(1, doc.xref_length()):
                            try:
                                xref_type = doc.xref_get_key(xref_num, "Type")
                                if xref_type[1] == "/XObject":
                                    subtype = doc.xref_get_key(xref_num, "Subtype")
                                    if subtype[1] == "/Form":
                                        # This is a form XObject
                                        try:
                                            # Check if this XObject contains watermark
                                            stream_bytes = doc.xref_stream(xref_num)
                                            if stream_bytes:
                                                try:
                                                    xobj_text = stream_bytes.decode('latin-1', errors='ignore').lower()
                                                    if any(wm_lower in xobj_text for wm_lower in watermark_lowers):
                                                        # Process this XObject
                                                        if process_form_xobject(doc, xref_num, watermark_lowers, page_num):
                                                            xobjects_found = True
                                                except:
                                                    pass
                                        except:
                                            pass
                            except:
                                continue
                        
                        # Alternative: Get XObjects from page resources directly
                        try:
                            # Get page object
                            page_obj = doc[page_num]
                            # Try to access resources/XObject
                            # This is complex, so we'll use the document-wide search above
                            pass
                        except:
                            pass
                            
                    except Exception as xobj_error:
                        if page_num < 3:
                            print(f"Debug: Page {page_num + 1} - XObject processing error: {xobj_error}", file=sys.stderr)
                    
                    # Also try processing XObjects by parsing the content stream for /Do operators
                    try:
                        # Find all XObject references in content stream: /XName Do
                        do_pattern = r'/(\w+)\s+Do\b'
                        xobj_refs = re.findall(do_pattern, stream_text)
                        
                        if xobj_refs and page_num < 3:
                            print(f"Debug: Page {page_num + 1} - Found XObject references: {xobj_refs[:3]}", file=sys.stderr)
                    except:
                        pass
                        
                except Exception as xobj_error:
                    if page_num < 3:
                        print(f"Debug: Page {page_num + 1} - Error accessing XObjects: {xobj_error}", file=sys.stderr)
                    pass
                
                # Extract text from PDF content stream more comprehensively
                def extract_all_text_from_stream(stream):
                    """Extract all readable text from PDF content stream"""
                    all_text = []
                    
                    # Extract literal strings: (text)
                    # Handle escaped characters properly
                    i = 0
                    while i < len(stream):
                        if stream[i] == '(':
                            j = i + 1
                            content = []
                            while j < len(stream):
                                if stream[j] == '\\' and j + 1 < len(stream):
                                    # Escape sequence
                                    esc_char = stream[j+1]
                                    if esc_char in '()nrtbf':
                                        content.append(esc_char)
                                    j += 2
                                elif stream[j] == ')':
                                    all_text.append(''.join(content))
                                    i = j + 1
                                    break
                                else:
                                    content.append(stream[j])
                                    j += 1
                            else:
                                i += 1
                        else:
                            i += 1
                    
                    # Extract hex strings: <hex>
                    hex_matches = re.findall(r'<([0-9A-Fa-f]+)>', stream)
                    for hex_str in hex_matches:
                        try:
                            if len(hex_str) % 2 == 0:
                                try:
                                    decoded = bytes.fromhex(hex_str).decode('utf-8', errors='ignore')
                                except:
                                    decoded = bytes.fromhex(hex_str).decode('latin-1', errors='ignore')
                                all_text.append(decoded)
                        except:
                            pass
                    
                    return ' '.join(all_text).lower()
                
                # More aggressive removal: remove any text object containing watermark
                # Pattern 1: BT...ET blocks
                text_object_pattern = r'BT(.*?)ET'
                
                def should_remove_text_object(match):
                    block = match.group(1)
                    extracted = extract_all_text_from_stream(block)
                    return any(wm_lower in extracted for wm_lower in watermark_lowers)
                
                new_stream_text = re.sub(text_object_pattern,
                                       lambda m: '' if should_remove_text_object(m) else m.group(0),
                                       new_stream_text, flags=re.DOTALL)
                
                # Pattern 2: Inline text operators
                def should_remove_inline(match):
                    text_str = match.group(1)
                    # Unescape the text
                    text_str = text_str.replace('\\\\(', '(').replace('\\\\)', ')')
                    text_str = text_str.replace('\\\\', '\\')
                    return any(wm_lower in text_str.lower() for wm_lower in watermark_lowers)
                
                # Remove (text) Tj
                new_stream_text = re.sub(r'\(([^)]*)\)\s+Tj\b',
                                       lambda m: '' if should_remove_inline(m) else m.group(0),
                                       new_stream_text)
                
                # Remove [array] TJ
                def should_remove_tj_array(match):
                    array_content = match.group(1)
                    extracted = extract_all_text_from_stream(array_content)
                    return any(wm_lower in extracted for wm_lower in watermark_lowers)
                
                new_stream_text = re.sub(r'\[([^\]]*)\]\s+TJ\b',
                                       lambda m: '' if should_remove_tj_array(m) else m.group(0),
                                       new_stream_text)
                
                # Remove (text) ' and (text) "
                new_stream_text = re.sub(r'\(([^)]*)\)\s+\'\b',
                                       lambda m: '' if should_remove_inline(m) else m.group(0),
                                       new_stream_text)
                new_stream_text = re.sub(r'\(([^)]*)\)\s+"\b',
                                       lambda m: '' if should_remove_inline(m) else m.group(0),
                                       new_stream_text)
                
                # Update content stream if modified
                if new_stream_text != original_stream:
                    changes_made = len(original_stream) - len(new_stream_text)
                    if page_num < 3:  # Debug first few pages
                        print(f"Debug: Page {page_num + 1} - Stream modified, removed {changes_made} bytes", file=sys.stderr)
                    
                    try:
                        # Get content xrefs
                        content_xrefs = page.get_contents()
                        if content_xrefs:
                            # Write modified stream
                            new_stream_bytes = new_stream_text.encode('latin-1', errors='ignore')
                            
                            # Method 1: Try updating without compression
                            success = False
                            try:
                                doc.update_stream(content_xrefs[0], new_stream_bytes, compress=False)
                                success = True
                                if page_num < 3:
                                    print(f"Debug: Page {page_num + 1} - Stream updated (no compression)", file=sys.stderr)
                            except Exception as e1:
                                # Method 2: Try with compression
                                try:
                                    doc.update_stream(content_xrefs[0], new_stream_bytes, compress=True)
                                    success = True
                                    if page_num < 3:
                                        print(f"Debug: Page {page_num + 1} - Stream updated (compressed)", file=sys.stderr)
                                except Exception as e2:
                                    # Method 3: Try alternative update
                                    try:
                                        # Use update_stream without compress parameter
                                        doc.update_stream(content_xrefs[0], new_stream_bytes)
                                        success = True
                                        if page_num < 3:
                                            print(f"Debug: Page {page_num + 1} - Stream updated (default)", file=sys.stderr)
                                    except Exception as e3:
                                        if page_num < 3:
                                            print(f"Debug: Page {page_num + 1} - All update methods failed: {e3}", file=sys.stderr)
                            
                            # Force page refresh if update succeeded
                            if success:
                                try:
                                    # Invalidate page cache
                                    page.clean_contents()
                                except:
                                    pass
                    except Exception as update_error:
                        if page_num < 3:
                            print(f"Debug: Update error on page {page_num + 1}: {update_error}", file=sys.stderr)
                        pass
                else:
                    if page_num < 3:
                        print(f"Debug: Page {page_num + 1} - No changes detected in stream", file=sys.stderr)
                        
            except Exception as stream_error:
                if page_num < 3:  # Debug first few pages
                    print(f"Debug: Stream error on page {page_num + 1}: {stream_error}", file=sys.stderr)
                pass
        
        doc.save(output_path, garbage=4, deflate=True)
        
        # Verify watermark removal
        if watermark_list:
            verify_doc = fitz.open(output_path)
            remaining_watermarks = []
            for page_num in range(len(verify_doc)):
                page = verify_doc[page_num]
                page_text = page.get_text().lower()
                for wm_lower in watermark_lowers:
                    if wm_lower in page_text:
                        remaining_watermarks.append((page_num + 1, wm_lower))
            verify_doc.close()
            
            if remaining_watermarks:
                print(f"Warning: Watermark still found on pages: {remaining_watermarks}", file=sys.stderr)
                print("Note: Some watermarks may be embedded as images or in form XObjects.", file=sys.stderr)
            else:
                print("Watermark removal verified successfully.", file=sys.stderr)
        
        doc.close()
        return True
    except Exception as e:
        print(f"Error processing PDF: {e}", file=sys.stderr)
        return False


def remove_watermark_pypdf(pdf_path, watermark_strings, output_path):
    """
    Remove watermark using pypdf (fallback method).
    Note: This method is less effective as pypdf has limited watermark removal capabilities.
    watermark_strings: list of watermark strings to remove, or None
    """
    try:
        reader = PdfReader(pdf_path)
        writer = PdfWriter()
        
        watermark_list = watermark_strings if watermark_strings else []
        watermark_lowers = [w.lower() for w in watermark_list] if watermark_list else []
        
        for page in reader.pages:
            # Try to remove annotations that might contain watermarks
            if "/Annots" in page:
                annots = page["/Annots"]
                if annots:
                    new_annots = []
                    for annot_ref in annots:
                        annot = annot_ref.get_object()
                        try:
                            content = annot.get("/Contents", "")
                            title = annot.get("/T", "")
                            if watermark_list:
                                content_lower = str(content).lower()
                                title_lower = str(title).lower()
                                if any(wm_lower in content_lower or wm_lower in title_lower for wm_lower in watermark_lowers):
                                    continue
                            new_annots.append(annot_ref)
                        except:
                            new_annots.append(annot_ref)
                    
                    if new_annots:
                        page["/Annots"] = new_annots
                    else:
                        del page["/Annots"]
            
            writer.add_page(page)
        
        with open(output_path, 'wb') as output_file:
            writer.write(output_file)
        
        return True
    except Exception as e:
        print(f"Error processing PDF: {e}", file=sys.stderr)
        return False


def main():
    parser = argparse.ArgumentParser(
        description='Remove watermarks from PDF files',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s -i document.pdf
  %(prog)s -i document.pdf -rs "CONFIDENTIAL"
  %(prog)s -i document.pdf -rs "test123" "test456"
  %(prog)s -i document.pdf -o output.pdf
        """
    )
    
    parser.add_argument(
        '-i', '--input',
        required=True,
        help='Input PDF file path'
    )
    
    parser.add_argument(
        '-rs', '--remove-string',
        nargs='+',
        default=None,
        help='Specific watermark text string(s) to remove (optional, will auto-detect if not provided). Can specify multiple strings: -rs "text1" "text2"'
    )
    
    parser.add_argument(
        '-o', '--output',
        default=None,
        help='Output PDF file path (default: <input_name>_remove_watermark.pdf)'
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
    
    # Determine output path
    if args.output:
        output_path = Path(args.output)
    else:
        # Default output is in the current working directory
        output_path = Path.cwd() / f"{input_path.stem}_remove_watermark.pdf"
    
    # Ensure output directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Determine watermark text(s)
    watermark_strings = args.remove_string
    
    if not watermark_strings:
        print("Auto-detecting watermark...", file=sys.stderr)
        detected_watermark = detect_watermark_text(input_path)
        if detected_watermark:
            watermark_strings = [detected_watermark]
            print(f"Detected watermark: '{detected_watermark}'", file=sys.stderr)
        else:
            print("Warning: Could not auto-detect watermark. Processing without specific watermark text.", file=sys.stderr)
            print("Note: For best results, specify watermark text with --remove-string", file=sys.stderr)
    
    if watermark_strings:
        watermark_display = ', '.join(f"'{w}'" for w in watermark_strings)
        print(f"Removing watermark(s): {watermark_display}", file=sys.stderr)
    
    # Remove watermark
    print(f"Processing PDF: {input_path}", file=sys.stderr)
    print(f"Output will be saved to: {output_path}", file=sys.stderr)
    
    # Use appropriate method based on available libraries
    if PYMUPDF_AVAILABLE:
        success = remove_watermark_pymupdf(input_path, watermark_strings, output_path)
    else:
        print("Warning: Using pypdf (limited watermark removal capabilities).", file=sys.stderr)
        print("For better results, install PyMuPDF: pip install pymupdf", file=sys.stderr)
        success = remove_watermark_pypdf(input_path, watermark_strings, output_path)
    
    if success:
        print(f"Successfully processed PDF. Output saved to: {output_path}")
    else:
        print("Error: Failed to process PDF", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
