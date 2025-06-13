import os
import base64
import pandas as pd
import google.generativeai as genai
from pathlib import Path
import json
import re
from typing import List, Dict, Optional
import io
import fitz  # PyMuPDF
import platform
import subprocess
import sys

# Optional imports for different PDF processing methods
try:
    from pdf2image import convert_from_path
    PDF2IMAGE_AVAILABLE = True
except ImportError:
    PDF2IMAGE_AVAILABLE = False
    print("pdf2image not available. Using PyMuPDF instead.")

try:
    import PyPDF2
    PYPDF2_AVAILABLE = True
except ImportError:
    PYPDF2_AVAILABLE = False

class PDFTableExtractor:
    def __init__(self, api_key: str):
        """
        Initialize the PDF Table Extractor with Gemini 2.0 Flash
        
        Args:
            api_key (str): Your Google AI API key
        """
        self.api_key = api_key
        genai.configure(api_key=api_key)
        
        # Initialize Gemini 2.0 Flash model
        self.model = genai.GenerativeModel('gemini-2.0-flash-exp')
        
        # Base output directory - will be set per PDF
        self.base_output_dir = Path("extracted_tables")
        self.base_output_dir.mkdir(exist_ok=True)
        self.output_dir = None  # Will be set when processing PDF
        
        # Check available PDF processing methods
        self.check_dependencies()
    
    def extract_pdf_title(self, pdf_path: str) -> str:
        """
        Extract title from PDF metadata or first page content
        
        Args:
            pdf_path (str): Path to the PDF file
            
        Returns:
            str: Extracted title or fallback name
        """
        try:
            doc = fitz.open(pdf_path)
            
            # First try to get title from metadata
            metadata = doc.metadata
            if metadata and metadata.get('title'):
                title = metadata['title'].strip()
                if title and len(title) > 3:  # Valid title
                    doc.close()
                    return self.sanitize_directory_name(title)
            
            # If no metadata title, try to extract from first page
            if len(doc) > 0:
                first_page = doc[0]
                
                # Get text blocks (title is usually in larger font at top)
                blocks = first_page.get_text("dict")
                
                # Look for the largest text in the upper portion of the page
                title_candidates = []
                page_height = first_page.rect.height
                
                for block in blocks.get("blocks", []):
                    if "lines" in block:
                        for line in block["lines"]:
                            bbox = line["bbox"]
                            y_pos = bbox[1]  # y coordinate
                            
                            # Only consider text in upper 30% of page
                            if y_pos < page_height * 0.3:
                                for span in line.get("spans", []):
                                    text = span.get("text", "").strip()
                                    font_size = span.get("size", 0)
                                    
                                    # Look for meaningful text with decent font size
                                    if (text and len(text) > 10 and 
                                        font_size >= 12 and 
                                        not text.lower().startswith(('page', 'confidential', 'draft'))):
                                        title_candidates.append((text, font_size, y_pos))
                
                # Sort by font size (descending) and y position (ascending - top first)
                title_candidates.sort(key=lambda x: (-x[1], x[2]))
                
                if title_candidates:
                    # Take the largest font text from the top
                    potential_title = title_candidates[0][0]
                    
                    # Clean up the title
                    potential_title = re.sub(r'\s+', ' ', potential_title.strip())
                    
                    # Remove common header patterns
                    potential_title = re.sub(r'^(COMPANY|CORPORATION|LIMITED|LTD|INC)[\s:]+', '', potential_title, flags=re.IGNORECASE)
                    
                    if len(potential_title) > 5:  # Valid title length
                        doc.close()
                        return self.sanitize_directory_name(potential_title)
            
            doc.close()
            
        except Exception as e:
            print(f"Error extracting PDF title: {e}")
        
        # Fallback to filename
        pdf_name = Path(pdf_path).stem
        return self.sanitize_directory_name(pdf_name)
    
    def sanitize_directory_name(self, name: str) -> str:
        """
        Sanitize a string to be used as a directory name
        
        Args:
            name (str): Original name
            
        Returns:
            str: Sanitized directory name
        """
        # Remove or replace invalid characters for directory names
        sanitized = re.sub(r'[<>:"/\\|?*]', '', name)
        
        # Replace multiple spaces with single space
        sanitized = re.sub(r'\s+', ' ', sanitized)
        
        # Remove leading/trailing spaces and dots
        sanitized = sanitized.strip(' .')
        
        # Limit length to avoid filesystem issues
        if len(sanitized) > 100:
            sanitized = sanitized[:100].strip()
        
        # If empty after sanitization, use fallback
        if not sanitized:
            sanitized = "Untitled_PDF"
        
        return sanitized
    
    def setup_output_directory(self, pdf_path: str):
        """
        Setup output directory based on PDF title
        
        Args:
            pdf_path (str): Path to the PDF file
        """
        # Extract title from PDF
        pdf_title = self.extract_pdf_title(pdf_path)
        
        # Create directory name with timestamp to avoid conflicts
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dir_name = f"{pdf_title}_{timestamp}"
        
        # Create the output directory
        self.output_dir = self.base_output_dir / dir_name
        self.output_dir.mkdir(exist_ok=True)
        
        print(f"📁 Created output directory: {self.output_dir}")
        print(f"📄 PDF Title detected: {pdf_title}")
    
    def check_dependencies(self):
        """Check and report available PDF processing methods"""
        print("Checking PDF processing dependencies...")
        
        methods = []
        if PDF2IMAGE_AVAILABLE:
            if self.check_poppler():
                methods.append("pdf2image + poppler")
                print("✓ pdf2image with poppler available")
            else:
                print("✗ pdf2image available but poppler not found")
        
        try:
            import fitz
            methods.append("PyMuPDF")
            print("✓ PyMuPDF available")
        except ImportError:
            print("✗ PyMuPDF not available")
        
        if not methods:
            print("⚠️  No PDF processing methods available. Installing PyMuPDF...")
            self.install_pymupdf()
        
        print(f"Available methods: {', '.join(methods)}")
    
    def check_poppler(self) -> bool:
        """Check if poppler is installed and accessible"""
        try:
            if platform.system() == "Windows":
                subprocess.run(["pdftoppm", "-h"], capture_output=True, check=True)
            else:
                subprocess.run(["which", "pdftoppm"], capture_output=True, check=True)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False
    
    def install_pymupdf(self):
        """Install PyMuPDF if not available"""
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "PyMuPDF"])
            print("✓ PyMuPDF installed successfully")
            global fitz
            import fitz
        except Exception as e:
            print(f"Failed to install PyMuPDF: {e}")
            raise Exception("No PDF processing library available. Please install either PyMuPDF or pdf2image with poppler.")
    
    def pdf_to_images_pymupdf(self, pdf_path: str) -> List[any]:
        """
        Convert PDF pages to images using PyMuPDF with enhanced quality
        
        Args:
            pdf_path (str): Path to the PDF file
            
        Returns:
            List of PIL Image objects
        """
        try:
            from PIL import Image
            doc = fitz.open(pdf_path)
            images = []
            
            for page_num in range(len(doc)):
                page = doc.load_page(page_num)
                # Convert to image with higher DPI for better text recognition
                mat = fitz.Matrix(3.0, 3.0)  # 3x zoom = 216 DPI for better accuracy
                pix = page.get_pixmap(matrix=mat, alpha=False)  # No alpha for cleaner text
                img_data = pix.tobytes("png")
                img = Image.open(io.BytesIO(img_data))
                
                # Convert to RGB if needed for better processing
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                
                images.append(img)
            
            doc.close()
            return images
            
        except Exception as e:
            print(f"Error converting PDF to images with PyMuPDF: {e}")
            return []
    
    def pdf_to_images_pdf2image(self, pdf_path: str) -> List[any]:
        """
        Convert PDF pages to images using pdf2image
        
        Args:
            pdf_path (str): Path to the PDF file
            
        Returns:
            List of PIL Image objects
        """
        try:
            if not PDF2IMAGE_AVAILABLE:
                raise Exception("pdf2image not available")
            
            images = convert_from_path(pdf_path, dpi=200)
            return images
        except Exception as e:
            print(f"Error converting PDF to images with pdf2image: {e}")
            return []
    
    def pdf_to_images(self, pdf_path: str) -> List[any]:
        """
        Convert PDF pages to images using available method
        
        Args:
            pdf_path (str): Path to the PDF file
            
        Returns:
            List of PIL Image objects
        """
        # Try PyMuPDF first (more reliable)
        try:
            import fitz
            images = self.pdf_to_images_pymupdf(pdf_path)
            if images:
                print(f"✓ Converted {len(images)} pages using PyMuPDF")
                return images
        except ImportError:
            pass
        
        # Fallback to pdf2image if available and poppler is installed
        if PDF2IMAGE_AVAILABLE and self.check_poppler():
            images = self.pdf_to_images_pdf2image(pdf_path)
            if images:
                print(f"✓ Converted {len(images)} pages using pdf2image")
                return images
        
        print("❌ Failed to convert PDF to images. Please install PyMuPDF or pdf2image with poppler.")
        return []
    
    def encode_image(self, image) -> str:
        """
        Encode PIL image to base64 string
        
        Args:
            image: PIL Image object
            
        Returns:
            Base64 encoded string
        """
        buffer = io.BytesIO()
        image.save(buffer, format='PNG')
        buffer.seek(0)
        return base64.b64encode(buffer.read()).decode('utf-8')
    
    def create_table_extraction_prompt(self) -> str:
        """
        Create the prompt for table extraction with enhanced title detection and Quarter/Nine Months format
        
        Returns:
            Formatted prompt string
        """
        prompt = """
        You are an expert PDF table extraction specialist. Analyze this image with extreme precision to extract EXACT data as it appears.

        CRITICAL INSTRUCTIONS FOR ACCURACY:

        STEP 1 - COMPLETE TITLE EXTRACTION:
        - Look for the COMPLETE title including ALL subtitle information
        - Extract titles like: "UNAUDITED CONSOLIDATED FINANCIAL RESULTS FOR THE QUARTER & NINE MONTHS ENDED DECEMBER 31, 2024"
        - ALWAYS include currency/unit information if present: "(Rs. In Lakhs)", "(Rs. In Crores)", etc.
        - Look for text that appears prominently above the table
        - Include any subtitle information that describes the table content
        - Example complete titles:
          * "UNAUDITED CONSOLIDATED FINANCIAL RESULTS FOR THE QUARTER & NINE MONTHS ENDED DECEMBER 31, 2024 (Rs. In Lakhs)"
          * "AUDITED STANDALONE FINANCIAL RESULTS FOR THE QUARTER & YEAR ENDED MARCH 31, 2025 (Rs. In Lakhs)"

        STEP 2 - CRITICAL TEXT RECOGNITION FOR SPECIFIC PATTERNS:
        - MOST IMPORTANT: Look for text patterns that start with a dash/hyphen (-)
        - Specifically look for: "- Deferred Tax Expenses / (Income)"
        - This text appears as an indented sub-item under Tax Expense
        - Extract this EXACTLY as: "- Deferred Tax Expenses / (Income)"
        - DO NOT convert this to "#NAME?" or any error message
        - DO NOT interpret the dash as a negative sign for numbers
        - DO NOT remove the dash or modify the text in any way
        - This is DESCRIPTIVE TEXT, not a formula or calculation

        STEP 3 - QUARTER AND NINE MONTHS COLUMN HANDLING:
        - Look for column headers that contain "Quarter Ended" and "Nine Months Ended"
        - Extract these headers exactly as they appear with dates
        - Examples of expected headers:
          * "Quarter Ended December 31, 2024"
          * "Nine Months Ended December 31, 2024"
          * "Quarter Ended December 31, 2023"
          * "Nine Months Ended December 31, 2023"
        - Preserve the exact format: "Quarter Ended [Date]" and "Nine Months Ended [Date]"
        - Look for additional qualifiers like "Reviewed" or "Unaudited" if present

        STEP 4 - GENERAL TEXT RECOGNITION:
        - Read ALL other text EXACTLY as written in the PDF
        - Pay special attention to negative values in parentheses: (123.45)
        - Look for dash symbols "-" which indicate zero or nil values (different from descriptive text)
        - Preserve all decimal points, commas, and formatting exactly
        - Look carefully at each character to avoid misreading

        STEP 5 - SERIAL NUMBER (Sr. No.) HANDLING:
        - Look for "Sr. No." or "S. No." in the header
        - Serial numbers in this table are: I, II, III, IV, V, VI, VII, VIII, IX (Roman numerals WITHOUT parentheses)
        - Extract EXACTLY as shown:
          * I for first row
          * II for second row  
          * III for third row
          * IV for fourth row
          * V for fifth row
          * VI for sixth row
          * VII for seventh row
          * VIII for eighth row
          * IX for ninth row
        - Do NOT add parentheses if they're not there
        - Do NOT convert to Arabic numbers

        STEP 6 - FINANCIAL DATA HANDLING:
        - Extract ALL numerical values exactly as shown
        - Preserve negative values in parentheses: (135.30), (121.26), (196.58), (552.77)
        - Keep dash symbols as "-" for zero/nil values (when used as data, not as text prefix)
        - Maintain exact decimal precision: 13,542.40, 18,790.26, etc.
        - Include commas in large numbers exactly as shown
        - Do NOT interpret or modify any values

        STEP 7 - COMPLEX TABLE STRUCTURE:
        - Handle multi-level row descriptions correctly
        - For items with sub-items (like "a) Cost of Materials", "b) Purchase"), extract the complete text
        - For indented items like "- Deferred Tax Expenses / (Income)", extract EXACTLY as shown
        - Maintain proper hierarchy and indentation information
        - Extract merged cells and sub-categories properly
        - Remember: Items starting with "- " are descriptive text, not calculations

        STEP 8 - COLUMN HEADERS WITH QUARTER/NINE MONTHS:
        - Extract ALL column headers exactly as shown with the specific format
        - Include headers like:
          * "Quarter Ended December 31, 2024 Reviewed"
          * "Nine Months Ended December 31, 2024 Reviewed"
          * "Quarter Ended December 31, 2023 Reviewed"
          * "Nine Months Ended December 31, 2023 Reviewed"
        - Preserve all header text including qualifiers like "Reviewed", "Unaudited", "Audited"
        - Maintain the exact format: "Quarter Ended [Date]" and "Nine Months Ended [Date]"

        STEP 9 - PRECISE DATA EXTRACTION:
        - Extract ALL visible text from each cell EXACTLY as shown
        - Maintain precise column alignment
        - Include empty cells as empty strings
        - Preserve the exact row and column structure
        - Handle merged cells appropriately
        - Don't modify or interpret the data - extract it exactly
        - NEVER convert valid descriptive text to error messages

        OUTPUT FORMAT - CRITICAL EXAMPLE FOR QUARTER/NINE MONTHS:
        {
            "has_tables": true/false,
            "tables": [
                {
                    "title": "UNAUDITED CONSOLIDATED FINANCIAL RESULTS FOR THE QUARTER & NINE MONTHS ENDED DECEMBER 31, 2024 (Rs. In Lakhs)",
                    "table_number": null,
                    "headers": ["Sr. No.", "Particulars", "Quarter Ended December 31, 2024 Reviewed", "Nine Months Ended December 31, 2024 Reviewed", "Quarter Ended December 31, 2023 Reviewed", "Nine Months Ended December 31, 2023 Reviewed"],
                    "data": [
                        ["I", "Revenue from Operations", "2,369.75", "27,490.52", "2,148.92", "24,117.03"],
                        ["II", "Other Income", "929.74", "1,779.25", "", ""],
                        ["III", "Total Revenue (I+II)", "27,490.52", "63,117.03", "", ""],
                        ["", "Expenses", "", "", "", ""],
                        ["a)", "Cost of Materials Consumed", "15,151.00", "31,781.99", "", ""],
                        ["b)", "Purchase of Traded Goods", "1,721.37", "5,110.47", "", ""],
                        ["c)", "Changes in Inventories of Finished Goods, Work-in-Progress and Stock-in", "829.82", "3,443.16", "", ""],
                        ["IV", "", "", "", "", ""],
                        ["d)", "Employee Benefits Expense", "1,936.50", "3,307.21", "", ""],
                        ["e)", "Manufacturing and Other Expenses", "3,051.79", "7,683.58", "", ""],
                        ["f)", "Finance Cost", "253.80", "554.75", "", ""],
                        ["g)", "Depreciation & Amortisation Expense", "254.70", "665.34", "", ""],
                        ["", "Total Expenses (a to g)", "22,777.28", "52,547.00", "", ""],
                        ["V", "Profit / (Loss) before Exceptional Items and Tax (III-IV)", "4,823.24", "10,570.03", "", ""],
                        ["VI", "Exceptional Items", "-", "-", "", ""],
                        ["VII", "Profit / (Loss) before Tax (V-VI)", "4,823.24", "10,570.03", "", ""],
                        ["VIII", "Tax Expense - Current Tax", "1,109.75", "2,360.00", "", ""],
                        ["", "- Deferred Tax Expenses / (Income)", "(0.52)", "(211.11)", "", ""],
                        ["IX", "Profit / (Loss) for the period (VII-VIII)", "3,632.51", "8,549.21", "", ""]
                    ]
                }
            ]
        }

        CRITICAL ACCURACY REQUIREMENTS:
        1. Include complete title with currency information: "(Rs. In Lakhs)"
        2. Extract Sr. No. as Roman numerals: I, II, III, IV, V, VI, VII, VIII, IX
        3. Preserve negative values in parentheses: (135.30), (121.26)
        4. Keep dash symbols as "-" for nil values in data cells
        5. Extract "- Deferred Tax Expenses / (Income)" EXACTLY as shown - this is descriptive text, not an error
        6. Maintain exact financial formatting with commas
        7. Extract all sub-item descriptions completely
        8. Use "Quarter Ended [Date]" and "Nine Months Ended [Date]" format for column headers
        9. Handle complex table structure with merged cells

        MOST IMPORTANT - AVOID THESE SPECIFIC MISTAKES:
        - Converting "- Deferred Tax Expenses / (Income)" to "#NAME?" or any error message
        - Treating "- Deferred Tax Expenses / (Income)" as a formula or calculation
        - Missing the complete descriptive text that starts with "-"
        - Converting descriptive text starting with "-" to numerical values
        - Not using the proper "Quarter Ended" and "Nine Months Ended" format in headers

        SPECIFIC TEXT PATTERNS TO PRESERVE EXACTLY:
        - "- Deferred Tax Expenses / (Income)" (this is descriptive text, not a calculation)
        - "- Current Tax" (if present)
        - Any other text that starts with "- " (these are descriptions, not formulas)
        - "Quarter Ended [Date]" format for quarterly columns
        - "Nine Months Ended [Date]" format for nine-month columns

        Remember: Text that starts with "- " followed by words is DESCRIPTIVE TEXT that should be extracted exactly as written, never converted to error messages. Column headers should use the exact "Quarter Ended" and "Nine Months Ended" format.
        """
        return prompt
    
    def extract_tables_from_image(self, image) -> Dict:
        """
        Extract tables from a single image using Gemini with enhanced error handling
        
        Args:
            image: PIL Image object
            
        Returns:
            Dictionary containing extraction results
        """
        try:
            prompt = self.create_table_extraction_prompt()
            
            # Generate content using Gemini 2.0 Flash with enhanced parameters
            generation_config = {
                'temperature': 0.1,  # Lower temperature for more consistent output
                'top_p': 0.8,
                'top_k': 40,
                'max_output_tokens': 8192,  # Increased for larger tables
            }
            
            response = self.model.generate_content(
                [prompt, image],
                generation_config=generation_config
            )
            
            # Parse the JSON response with better error handling
            response_text = response.text.strip()
            
            # Multiple cleaning attempts for robust parsing
            if response_text.startswith('```json'):
                response_text = response_text[7:-3].strip()
            elif response_text.startswith('```'):
                response_text = response_text[3:-3].strip()
            elif response_text.startswith('json'):
                response_text = response_text[4:].strip()
            
            # Remove any trailing markdown
            if response_text.endswith('```'):
                response_text = response_text[:-3].strip()
            
            try:
                result = json.loads(response_text)
                
                # Validate the result structure
                if not isinstance(result, dict):
                    print(f"Invalid response format: not a dictionary")
                    return {"has_tables": False, "tables": []}
                
                if "has_tables" not in result:
                    print(f"Missing 'has_tables' key in response")
                    return {"has_tables": False, "tables": []}
                
                if result.get("has_tables") and "tables" not in result:
                    print(f"Missing 'tables' key when has_tables is true")
                    return {"has_tables": False, "tables": []}
                
                # Validate each table structure
                if result.get("has_tables") and result.get("tables"):
                    valid_tables = []
                    for i, table in enumerate(result["tables"]):
                        if not isinstance(table, dict):
                            print(f"Table {i+1}: Invalid table format")
                            continue
                        
                        # Ensure required keys exist
                        if "headers" not in table:
                            table["headers"] = []
                        if "data" not in table:
                            table["data"] = []
                        if "title" not in table:
                            table["title"] = None
                        
                        valid_tables.append(table)
                    
                    result["tables"] = valid_tables
                
                return result
                
            except json.JSONDecodeError as e:
                print(f"JSON parsing error: {e}")
                print(f"Raw response (first 500 chars): {response_text[:500]}")
                
                # Attempt to fix common JSON issues
                try:
                    # Try to fix incomplete JSON
                    if not response_text.endswith('}') and not response_text.endswith(']'):
                        response_text += '}'
                    
                    # Try parsing again
                    result = json.loads(response_text)
                    return result
                except:
                    print(f"Failed to recover from JSON error")
                    return {"has_tables": False, "tables": []}
                
        except Exception as e:
            print(f"Error extracting tables from image: {e}")
            import traceback
            print(f"Full traceback: {traceback.format_exc()}")
            return {"has_tables": False, "tables": []}
    
    def save_table_to_csv(self, table_data: Dict, page_num: int, table_num: int, pdf_name: str) -> str:
        """
        Save extracted table data to CSV file with title
        
        Args:
            table_data (Dict): Table data dictionary
            page_num (int): Page number
            table_num (int): Table number on the page
            pdf_name (str): Original PDF filename
            
        Returns:
            Path to saved CSV file
        """
        try:
            # Create filename based on the actual extracted title
            title = table_data.get('title', '')
            if title:
                # Clean title for filename - remove special characters but keep structure
                safe_filename = re.sub(r'[<>:"/\\|?*]', '', title)  # Remove only Windows invalid chars
                safe_filename = safe_filename.replace('(Rs. In Lakhs)', '').strip()  # Remove currency part
                safe_filename = re.sub(r'\s+', ' ', safe_filename)  # Normalize spaces
                
                # Use the cleaned title as filename
                filename = f"{safe_filename}.csv"
            else:
                # Fallback filename
                filename = f"{pdf_name}_page{page_num}_table{table_num}_Table.csv"
            
            filepath = self.output_dir / filename
            
            # Get headers and data
            headers = table_data.get('headers', [])
            data = table_data.get('data', [])
            
            if not data:
                print(f"No data found in table: {table_data.get('title', 'Unknown')}")
                return None
            
            # Fix data to prevent Excel #NAME? errors
            def fix_excel_formula_issues(cell_value):
                """Fix cell values that might be interpreted as formulas by Excel"""
                if isinstance(cell_value, str):
                    # If text starts with dash and contains letters, add single quote to prevent formula interpretation
                    if cell_value.startswith('-') and any(c.isalpha() for c in cell_value):
                        return f"'{cell_value}"
                    # If text starts with = or +, add single quote
                    elif cell_value.startswith(('=', '+')):
                        return f"'{cell_value}"
                return cell_value
            
            # Apply fix to all data
            fixed_data = []
            for row in data:
                fixed_row = [fix_excel_formula_issues(cell) for cell in row]
                fixed_data.append(fixed_row)
            
            # Handle column mismatch between headers and data
            if headers and fixed_data:
                # Find the maximum number of columns in the data
                max_data_cols = max(len(row) for row in fixed_data) if fixed_data else 0
                
                # Adjust headers to match data columns
                if len(headers) > max_data_cols:
                    # Too many headers - truncate headers
                    headers = headers[:max_data_cols]
                    print(f"  Adjusted headers: reduced from {len(table_data.get('headers', []))} to {len(headers)} columns")
                elif len(headers) < max_data_cols:
                    # Too few headers - add generic column names
                    for i in range(len(headers), max_data_cols):
                        headers.append(f"Column_{i+1}")
                    print(f"  Adjusted headers: expanded from {len(table_data.get('headers', []))} to {len(headers)} columns")
                
                # Ensure all data rows have the same number of columns as headers
                adjusted_data = []
                for row in fixed_data:
                    if len(row) > len(headers):
                        # Too many columns in row - truncate
                        adjusted_row = row[:len(headers)]
                    elif len(row) < len(headers):
                        # Too few columns in row - pad with empty strings
                        adjusted_row = row + [''] * (len(headers) - len(row))
                    else:
                        adjusted_row = row
                    adjusted_data.append(adjusted_row)
                
                # Create DataFrame with adjusted data
                df = pd.DataFrame(adjusted_data, columns=headers)
                
            elif fixed_data:
                # No headers provided - use data as is with generic column names
                max_cols = max(len(row) for row in fixed_data)
                
                # Ensure all rows have the same number of columns
                adjusted_data = []
                for row in fixed_data:
                    if len(row) < max_cols:
                        adjusted_row = row + [''] * (max_cols - len(row))
                    else:
                        adjusted_row = row[:max_cols]
                    adjusted_data.append(adjusted_row)
                
                df = pd.DataFrame(adjusted_data)
                print(f"  No headers provided - created table with {len(df.columns)} columns")
            else:
                print(f"No valid data found in table: {table_data.get('title', 'Unknown')}")
                return None
            
            # Save to CSV with title at the top
            with open(filepath, 'w', newline='', encoding='utf-8') as csvfile:
                # Add title as first row if available
                title = table_data.get('title')
                if title:
                    csvfile.write(f'"{title}"\n')
                    csvfile.write('\n')  # Empty line after title
                    print(f"  Added title: {title}")
                
                # Write the DataFrame to CSV
                df.to_csv(csvfile, index=False)
            
            print(f"✓ Saved table: {filepath}")
            print(f"  Final table size: {len(df)} rows × {len(df.columns)} columns")
            print(f"  Fixed Excel formula interpretation issues")
            
            return str(filepath)
            
        except Exception as e:
            print(f"Error saving table to CSV: {e}")
            print(f"  Headers count: {len(table_data.get('headers', []))}")
            print(f"  Data rows: {len(table_data.get('data', []))}")
            if table_data.get('data'):
                print(f"  Max columns in data: {max(len(row) for row in table_data.get('data', []))}")
            return None
    
    def process_pdf(self, pdf_path: str) -> Dict:
        """
        Process entire PDF and extract all tables
        
        Args:
            pdf_path (str): Path to PDF file
            
        Returns:
            Dictionary with processing results
        """
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")
        
        # Setup output directory based on PDF title
        self.setup_output_directory(str(pdf_path))
        
        pdf_name = pdf_path.stem
        print(f"Processing PDF: {pdf_name}")
        
        # Convert PDF to images
        images = self.pdf_to_images(str(pdf_path))
        if not images:
            return {
                "error": "Failed to convert PDF to images",
                "pdf_name": pdf_name,
                "total_pages": 0,
                "pages_with_tables": 0,
                "total_tables_extracted": 0,
                "csv_files": [],
                "page_results": []
            }
        
        results = {
            "pdf_name": pdf_name,
            "output_directory": str(self.output_dir),
            "total_pages": len(images),
            "pages_with_tables": 0,
            "total_tables_extracted": 0,
            "csv_files": [],
            "page_results": [],
            "extracted_titles": []  # Track extracted titles
        }
        
        # Dictionary to store tables by title for combining
        tables_by_title = {}
        
        # Process each page
        for page_num, image in enumerate(images, 1):
            print(f"\nProcessing page {page_num}/{len(images)}...")
            
            try:
                # Extract tables from current page
                extraction_result = self.extract_tables_from_image(image)
                
                page_result = {
                    "page_number": page_num,
                    "has_tables": extraction_result.get("has_tables", False),
                    "tables_count": len(extraction_result.get("tables", [])),
                    "tables": []
                }
                
                if extraction_result.get("has_tables", False):
                    results["pages_with_tables"] += 1
                    tables = extraction_result.get("tables", [])
                    
                    for table_num, table_data in enumerate(tables, 1):
                        title = table_data.get('title', 'Untitled Table')
                        print(f"  Found table: {title}")
                        
                        # Track extracted titles
                        if table_data.get('title'):
                            results["extracted_titles"].append(table_data.get('title'))
                        
                        # Enhanced title normalization for better continuation detection
                        normalized_title = self.normalize_title_for_grouping(title, page_num)
                        
                        # Group tables by normalized title
                        if normalized_title not in tables_by_title:
                            tables_by_title[normalized_title] = {
                                "title": title,
                                "headers": table_data.get('headers', []),
                                "data": table_data.get('data', []),
                                "pages": [page_num],
                                "table_numbers": [table_num],
                                "original_titles": [title]
                            }
                            print(f"    Created new table group: {normalized_title}")
                        else:
                            # Combine data from continuation pages
                            existing_table = tables_by_title[normalized_title]
                            
                            # Check if headers are similar (for continuation detection)
                            if self.are_headers_compatible(existing_table["headers"], table_data.get('headers', [])):
                                existing_table["data"].extend(table_data.get('data', []))
                                existing_table["pages"].append(page_num)
                                existing_table["table_numbers"].append(table_num)
                                existing_table["original_titles"].append(title)
                                print(f"    Added continuation data to existing table: {normalized_title}")
                                print(f"    Combined data from pages: {existing_table['pages']}")
                            else:
                                # Different table structure, create new entry
                                alt_normalized_title = f"{normalized_title}_v{len([k for k in tables_by_title.keys() if k.startswith(normalized_title)])+1}"
                                tables_by_title[alt_normalized_title] = {
                                    "title": title,
                                    "headers": table_data.get('headers', []),
                                    "data": table_data.get('data', []),
                                    "pages": [page_num],
                                    "table_numbers": [table_num],
                                    "original_titles": [title]
                                }
                                print(f"    Created variant table group: {alt_normalized_title}")
                        
                        page_result["tables"].append({
                            "title": table_data.get("title"),
                            "table_number": table_data.get("table_number"),
                            "normalized_title": normalized_title,
                            "rows": len(table_data.get("data", [])),
                            "columns": len(table_data.get("headers", []))
                        })
                else:
                    print(f"  No tables found on page {page_num}")
                
                results["page_results"].append(page_result)
                
            except Exception as e:
                print(f"  Error processing page {page_num}: {e}")
                page_result = {
                    "page_number": page_num,
                    "has_tables": False,
                    "tables_count": 0,
                    "tables": [],
                    "error": str(e)
                }
                results["page_results"].append(page_result)
        
        # Now save the combined tables
        print(f"\nCombining and saving tables...")
        for normalized_title, combined_table in tables_by_title.items():
            print(f"\nSaving combined table: {normalized_title}")
            print(f"  Pages: {combined_table['pages']}")
            print(f"  Total rows: {len(combined_table['data'])}")
            print(f"  Original titles: {combined_table['original_titles']}")
            
            # Save the combined table
            csv_path = self.save_combined_table_to_csv(combined_table, pdf_name)
            
            if csv_path:
                results["csv_files"].append(csv_path)
                results["total_tables_extracted"] += 1
        
        return results
    
    def normalize_title_for_grouping(self, title: str, page_num: int) -> str:
        """
        Normalize title for better grouping of continuation tables
        
        Args:
            title (str): Original title
            page_num (int): Page number
            
        Returns:
            str: Normalized title for grouping
        """
        if not title or title.strip() == '':
            return f"Table_Page_{page_num}"
        
        # Remove extra spaces and normalize
        normalized = re.sub(r'\s+', ' ', title.strip())
        
        # Remove common continuation indicators
        continuation_patterns = [
            r'\s*\(continued\)',
            r'\s*\(contd\)',
            r'\s*\(cont\)',
            r'\s*continued',
            r'\s*contd',
            r'\s*\-\s*continued',
            r'\s*\-\s*contd',
            r'page\s*\d+',
            r'sheet\s*\d+'
        ]
        
        for pattern in continuation_patterns:
            normalized = re.sub(pattern, '', normalized, flags=re.IGNORECASE)
        
        # Normalize company name variations and Quarter/Nine Months patterns
        company_patterns = [
            (r'HDFC\s+Life\s+Insurance\s+Company\s+Limited?', 'HDFC Life Insurance Company Limited'),
            (r'LLOYDS\s+ENGINEERING\s+WORKS\s+LIMITED', 'LLOYDS ENGINEERING WORKS LIMITED'),
            (r'Statement\s+of\s+Standalone\s+Audited\s+Results', 'Statement of Standalone Audited Results'),
            (r'UNAUDITED\s+CONSOLIDATED\s+FINANCIAL\s+RESULTS', 'UNAUDITED CONSOLIDATED FINANCIAL RESULTS'),
            (r'for\s+the\s+Quarter\s+and\s+Year\s+ended', 'for the Quarter and Year ended'),
            (r'for\s+the\s+Quarter\s+&\s+Nine\s+Months\s+ended', 'for the Quarter & Nine Months ended'),
            (r'for\s+the\s+Quarter\s+&\s+Year\s+ended', 'for the Quarter & Year ended'),
            (r'March\s+31,?\s*2025', 'March 31, 2025'),
            (r'December\s+31,?\s*2024', 'December 31, 2024'),
            (r'₹\s*in\s*Lakhs?', '₹ in Lakhs'),
            (r'Rs\.?\s*in\s*Lakhs?', 'Rs. in Lakhs')
        ]
        
        for pattern, replacement in company_patterns:
            normalized = re.sub(pattern, replacement, normalized, flags=re.IGNORECASE)
        
        # Handle similar financial statement titles with Quarter/Nine Months format
        if 'financial results' in normalized.lower() or 'audited results' in normalized.lower():
            # Group similar financial statements together
            if 'quarter' in normalized.lower() and 'nine months' in normalized.lower():
                # For Quarter & Nine Months format
                if 'lloyds' in normalized.lower() and 'consolidated' in normalized.lower():
                    normalized = "LLOYDS ENGINEERING WORKS LIMITED UNAUDITED CONSOLIDATED FINANCIAL RESULTS for the Quarter & Nine Months ended December 31, 2024"
            elif 'hdfc' in normalized.lower() and 'standalone' in normalized.lower():
                normalized = "HDFC Life Insurance Company Limited Statement of Standalone Audited Results for the Quarter and Year ended March 31, 2025"
        
        return normalized.strip()
    
    def are_headers_compatible(self, headers1: List, headers2: List) -> bool:
        """
        Check if two header sets are compatible for table continuation
        
        Args:
            headers1 (List): First set of headers
            headers2 (List): Second set of headers
            
        Returns:
            bool: True if headers are compatible
        """
        if not headers1 or not headers2:
            return True  # Allow if one has no headers
        
        # Normalize headers for comparison
        norm_headers1 = [re.sub(r'\s+', ' ', str(h).strip().lower()) for h in headers1]
        norm_headers2 = [re.sub(r'\s+', ' ', str(h).strip().lower()) for h in headers2]
        
        # Check if headers are identical or very similar
        if norm_headers1 == norm_headers2:
            return True
        
        # Check if headers have significant overlap (at least 70%)
        if len(norm_headers1) > 0 and len(norm_headers2) > 0:
            common_headers = set(norm_headers1) & set(norm_headers2)
            overlap_ratio = len(common_headers) / max(len(norm_headers1), len(norm_headers2))
            
            if overlap_ratio >= 0.7:  # 70% similarity
                return True
        
        # Check if one set is a subset of the other (for partial headers)
        if set(norm_headers1).issubset(set(norm_headers2)) or set(norm_headers2).issubset(set(norm_headers1)):
            return True
        
        # Check for common financial statement header patterns including Quarter/Nine Months
        financial_keywords = ['particulars', 'sr. no', 'march', 'december', 'audited', 'reviewed', 'quarter ended', 'nine months ended']
        headers1_has_financial = any(keyword in ' '.join(norm_headers1) for keyword in financial_keywords)
        headers2_has_financial = any(keyword in ' '.join(norm_headers2) for keyword in financial_keywords)
        
        if headers1_has_financial and headers2_has_financial:
            return True
        
        return False
    
    def save_combined_table_to_csv(self, combined_table: Dict, pdf_name: str) -> str:
        """
        Save combined table data to CSV file
        
        Args:
            combined_table (Dict): Combined table data dictionary
            pdf_name (str): Original PDF filename
            
        Returns:
            Path to saved CSV file
        """
        try:
            # Create filename based on the actual extracted title
            title = combined_table.get('title', '')
            if title:
                # Clean title for filename - remove special characters but keep structure
                safe_filename = re.sub(r'[<>:"/\\|?*]', '', title)  # Remove only Windows invalid chars
                safe_filename = safe_filename.replace('(Rs. In Lakhs)', '').strip()  # Remove currency part
                safe_filename = re.sub(r'\s+', ' ', safe_filename)  # Normalize spaces
                
                # Use the cleaned title as filename
                filename = f"{safe_filename}.csv"
            else:
                # Fallback filename
                filename = f"{pdf_name}_Combined_Table.csv"
            
            filepath = self.output_dir / filename
            
            # Get headers and data
            headers = combined_table.get('headers', [])
            data = combined_table.get('data', [])
            
            if not data:
                print(f"No data found in combined table: {title}")
                return None
            
            # Fix data to prevent Excel #NAME? errors
            def fix_excel_formula_issues(cell_value):
                """Fix cell values that might be interpreted as formulas by Excel"""
                if isinstance(cell_value, str):
                    # If text starts with dash and contains letters, add single quote to prevent formula interpretation
                    if cell_value.startswith('-') and any(c.isalpha() for c in cell_value):
                        return f"'{cell_value}"
                    # If text starts with = or +, add single quote
                    elif cell_value.startswith(('=', '+')):
                        return f"'{cell_value}"
                return cell_value
            
            # Apply fix to all data
            fixed_data = []
            for row in data:
                fixed_row = [fix_excel_formula_issues(cell) for cell in row]
                fixed_data.append(fixed_row)
            
            # Handle column mismatch between headers and data
            if headers and fixed_data:
                # Find the maximum number of columns in the data
                max_data_cols = max(len(row) for row in fixed_data) if fixed_data else 0
                
                # Adjust headers to match data columns
                if len(headers) > max_data_cols:
                    # Too many headers - truncate headers
                    headers = headers[:max_data_cols]
                    print(f"  Adjusted headers: reduced from original to {len(headers)} columns")
                elif len(headers) < max_data_cols:
                    # Too few headers - add generic column names
                    for i in range(len(headers), max_data_cols):
                        headers.append(f"Column_{i+1}")
                    print(f"  Adjusted headers: expanded to {len(headers)} columns")
                
                # Ensure all data rows have the same number of columns as headers
                adjusted_data = []
                for row in fixed_data:
                    if len(row) > len(headers):
                        # Too many columns in row - truncate
                        adjusted_row = row[:len(headers)]
                    elif len(row) < len(headers):
                        # Too few columns in row - pad with empty strings
                        adjusted_row = row + [''] * (len(headers) - len(row))
                    else:
                        adjusted_row = row
                    adjusted_data.append(adjusted_row)
                
                # Create DataFrame with adjusted data
                df = pd.DataFrame(adjusted_data, columns=headers)
                
            elif fixed_data:
                # No headers provided - use data as is with generic column names
                max_cols = max(len(row) for row in fixed_data)
                
                # Ensure all rows have the same number of columns
                adjusted_data = []
                for row in fixed_data:
                    if len(row) < max_cols:
                        adjusted_row = row + [''] * (max_cols - len(row))
                    else:
                        adjusted_row = row[:max_cols]
                    adjusted_data.append(adjusted_row)
                
                df = pd.DataFrame(adjusted_data)
                print(f"  No headers provided - created table with {len(df.columns)} columns")
            else:
                print(f"No valid data found in combined table: {title}")
                return None
            
            # Save to CSV with title at the top
            with open(filepath, 'w', newline='', encoding='utf-8') as csvfile:
                # Add title as first row if available
                title = combined_table.get('title')
                if title:
                    csvfile.write(f'"{title}"\n')
                    csvfile.write('\n')  # Empty line after title
                    print(f"  Added title: {title}")
                
                # Add note about combined pages
                pages = combined_table.get('pages', [])
                if len(pages) > 1:
                    csvfile.write(f'"Combined from pages: {", ".join(map(str, pages))}"\n')
                    csvfile.write('\n')  # Empty line after note
                    print(f"  Added page info: Combined from pages {pages}")
                
                # Write the DataFrame to CSV
                df.to_csv(csvfile, index=False)
            
            print(f"✓ Saved combined table: {filepath}")
            print(f"  Final combined table size: {len(df)} rows × {len(df.columns)} columns")
            print(f"  Fixed Excel formula interpretation issues")
            
            return str(filepath)
            
        except Exception as e:
            print(f"Error saving combined table to CSV: {e}")
            return None
    
    def generate_summary_report(self, results: Dict) -> str:
        """
        Generate a summary report of extraction results
        
        Args:
            results (Dict): Processing results
            
        Returns:
            Path to summary report file
        """
        report_path = self.output_dir / f"{results['pdf_name']}_extraction_summary.txt"
        
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(f"PDF Table Extraction Summary\n")
            f.write(f"=" * 50 + "\n\n")
            f.write(f"PDF File: {results['pdf_name']}\n")
            f.write(f"Output Directory: {results['output_directory']}\n")
            f.write(f"Total Pages: {results['total_pages']}\n")
            f.write(f"Pages with Tables: {results['pages_with_tables']}\n")
            f.write(f"Total Tables Extracted: {results['total_tables_extracted']}\n\n")
            
            # Show extracted titles
            if results.get('extracted_titles'):
                f.write("Extracted Titles from PDF:\n")
                f.write("-" * 30 + "\n")
                for i, title in enumerate(results['extracted_titles'], 1):
                    f.write(f"{i}. {title}\n")
                f.write("\n")
            
            f.write("Extracted CSV Files:\n")
            f.write("-" * 30 + "\n")
            for csv_file in results['csv_files']:
                f.write(f"• {csv_file}\n")
            
            f.write(f"\nDetailed Page Results:\n")
            f.write("-" * 30 + "\n")
            for page_result in results['page_results']:
                f.write(f"Page {page_result['page_number']}: ")
                if page_result['has_tables']:
                    f.write(f"{page_result['tables_count']} table(s) found\n")
                    for table in page_result['tables']:
                        f.write(f"  - {table['title']} ({table['rows']} rows, {table['columns']} cols)\n")
                else:
                    f.write("No tables\n")
        
        return str(report_path)