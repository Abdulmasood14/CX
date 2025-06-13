from flask import Flask, render_template, request, jsonify, send_file, send_from_directory
import os
import json
import zipfile
from werkzeug.utils import secure_filename
from pathlib import Path
import tempfile
import shutil
from datetime import datetime
import uuid
import traceback
import sys

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB max file size
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['SECRET_KEY'] = 'your-secret-key-here'

# Create upload directory if it doesn't exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Store extraction results temporarily
extraction_results = {}

@app.route('/')
def index():
    """Main page with upload form"""
    try:
        return render_template('index.html')
    except Exception as e:
        print(f"Error rendering template: {e}")
        return f"Template error: {e}", 500

@app.route('/health')
def health_check():
    """Simple health check endpoint"""
    return jsonify({'status': 'healthy', 'message': 'Server is running'})

@app.route('/test')
def test_route():
    """Test route to verify basic functionality"""
    return jsonify({'success': True, 'message': 'Flask app is working correctly'})

@app.route('/upload', methods=['POST'])
def upload_file():
    """Handle PDF file upload and extraction"""
    try:
        print("=== UPLOAD REQUEST RECEIVED ===")
        print(f"Request method: {request.method}")
        print(f"Request files: {list(request.files.keys())}")
        print(f"Request form: {list(request.form.keys())}")
        
        # Basic validation
        if 'file' not in request.files:
            print("ERROR: No file in request")
            return jsonify({'error': 'No file selected'}), 400
        
        file = request.files['file']
        api_key = request.form.get('api_key', '').strip()
        
        print(f"File: {file.filename if file else 'None'}")
        print(f"API Key length: {len(api_key) if api_key else 0}")
        
        if not file or file.filename == '':
            print("ERROR: Empty filename")
            return jsonify({'error': 'No file selected'}), 400
        
        if not api_key:
            print("ERROR: No API key provided")
            return jsonify({'error': 'Google AI API key is required'}), 400
        
        if not file.filename.lower().endswith('.pdf'):
            print("ERROR: Not a PDF file")
            return jsonify({'error': 'Please upload a PDF file'}), 400
        
        # Test imports first
        try:
            print("=== TESTING IMPORTS ===")
            import google.generativeai as genai
            print("✓ google.generativeai imported")
            
            from pdf_extractor import PDFTableExtractor
            print("✓ PDFTableExtractor imported")
            
        except ImportError as import_error:
            print(f"IMPORT ERROR: {import_error}")
            traceback.print_exc()
            return jsonify({'error': f'Missing dependency: {str(import_error)}. Please check server setup.'}), 500
        
        # Test API key
        try:
            print("=== TESTING API KEY ===")
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel('gemini-2.0-flash-exp')
            print("✓ API key configured successfully")
            
        except Exception as api_error:
            print(f"API ERROR: {api_error}")
            return jsonify({'error': f'Invalid Google AI API key: {str(api_error)}'}), 400
        
        # Generate unique ID
        extraction_id = str(uuid.uuid4())
        print(f"Generated extraction ID: {extraction_id}")
        
        # Save uploaded file
        try:
            filename = secure_filename(file.filename)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            unique_filename = f"{timestamp}_{filename}"
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
            
            print(f"Saving file to: {filepath}")
            file.save(filepath)
            print(f"✓ File saved successfully, size: {os.path.getsize(filepath)} bytes")
            
        except Exception as save_error:
            print(f"FILE SAVE ERROR: {save_error}")
            return jsonify({'error': f'Failed to save file: {str(save_error)}'}), 500
        
        # Process PDF
        try:
            print("=== INITIALIZING PDF EXTRACTOR ===")
            extractor = PDFTableExtractor(api_key)
            print("✓ Extractor initialized")
            
            print("=== PROCESSING PDF ===")
            results = extractor.process_pdf(filepath)
            print(f"✓ PDF processing completed")
            print(f"Results type: {type(results)}")
            print(f"Results keys: {list(results.keys()) if isinstance(results, dict) else 'Not a dict'}")
            
            if isinstance(results, dict) and "error" in results:
                print(f"Processing returned error: {results['error']}")
                return jsonify({'error': f'PDF processing failed: {results["error"]}'}), 500
            
            # Store results
            extraction_results[extraction_id] = {
                'results': results,
                'filepath': filepath,
                'extractor': extractor,
                'timestamp': datetime.now().isoformat()
            }
            print("✓ Results stored")
            
            # Clean up file
            try:
                os.remove(filepath)
                print("✓ Temporary file cleaned up")
            except Exception as cleanup_error:
                print(f"Cleanup warning: {cleanup_error}")
            
            # Prepare response
            response_data = {
                'success': True,
                'extraction_id': extraction_id,
                'results': {
                    'pdf_name': results.get('pdf_name', 'Unknown'),
                    'total_pages': results.get('total_pages', 0),
                    'pages_with_tables': results.get('pages_with_tables', 0),
                    'total_tables_extracted': results.get('total_tables_extracted', 0),
                    'extracted_titles': results.get('extracted_titles', []),
                    'csv_files': [os.path.basename(f) for f in results.get('csv_files', [])]
                }
            }
            
            print(f"✓ Returning success response")
            return jsonify(response_data)
            
        except Exception as process_error:
            print(f"PROCESSING ERROR: {process_error}")
            traceback.print_exc()
            
            # Clean up on error
            try:
                if os.path.exists(filepath):
                    os.remove(filepath)
            except:
                pass
            
            return jsonify({'error': f'PDF processing failed: {str(process_error)}'}), 500
        
    except Exception as e:
        print(f"GENERAL ERROR: {e}")
        traceback.print_exc()
        return jsonify({'error': f'Server error: {str(e)}'}), 500

@app.route('/download/<extraction_id>')
def download_results(extraction_id):
    """Download all CSV files as a ZIP archive"""
    try:
        if extraction_id not in extraction_results:
            return jsonify({'error': 'Extraction results not found'}), 404
        
        extraction_data = extraction_results[extraction_id]
        results = extraction_data['results']
        
        if not results.get('csv_files'):
            return jsonify({'error': 'No CSV files available for download'}), 404
        
        # Create temporary ZIP file
        temp_dir = tempfile.mkdtemp()
        zip_filename = f"{results['pdf_name']}_extracted_tables.zip"
        zip_path = os.path.join(temp_dir, zip_filename)
        
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for csv_file in results['csv_files']:
                if os.path.exists(csv_file):
                    arcname = os.path.basename(csv_file)
                    zipf.write(csv_file, arcname)
        
        return send_file(
            zip_path,
            as_attachment=True,
            download_name=zip_filename,
            mimetype='application/zip'
        )
        
    except Exception as e:
        print(f"Download error: {e}")
        return jsonify({'error': f'Download error: {str(e)}'}), 500

@app.route('/download_csv/<extraction_id>/<filename>')
def download_single_csv(extraction_id, filename):
    """Download a single CSV file"""
    try:
        if extraction_id not in extraction_results:
            return jsonify({'error': 'Extraction results not found'}), 404
        
        extraction_data = extraction_results[extraction_id]
        results = extraction_data['results']
        
        for csv_file in results.get('csv_files', []):
            if os.path.basename(csv_file) == filename:
                if os.path.exists(csv_file):
                    return send_file(
                        csv_file,
                        as_attachment=True,
                        download_name=filename,
                        mimetype='text/csv'
                    )
        
        return jsonify({'error': 'CSV file not found'}), 404
        
    except Exception as e:
        print(f"CSV download error: {e}")
        return jsonify({'error': f'Download error: {str(e)}'}), 500

@app.route('/status/<extraction_id>')
def get_status(extraction_id):
    """Get extraction status and results"""
    try:
        if extraction_id not in extraction_results:
            return jsonify({'error': 'Extraction not found'}), 404
        
        extraction_data = extraction_results[extraction_id]
        results = extraction_data['results']
        
        return jsonify({
            'success': True,
            'results': {
                'pdf_name': results.get('pdf_name', 'Unknown'),
                'total_pages': results.get('total_pages', 0),
                'pages_with_tables': results.get('pages_with_tables', 0),
                'total_tables_extracted': results.get('total_tables_extracted', 0),
                'extracted_titles': results.get('extracted_titles', []),
                'csv_files': [os.path.basename(f) for f in results.get('csv_files', [])],
                'timestamp': extraction_data['timestamp']
            }
        })
        
    except Exception as e:
        print(f"Status error: {e}")
        return jsonify({'error': f'Status error: {str(e)}'}), 500

@app.route('/cleanup')
def cleanup_old_results():
    """Clean up old extraction results"""
    try:
        current_time = datetime.now()
        to_remove = []
        
        for extraction_id, data in extraction_results.items():
            extraction_time = datetime.fromisoformat(data['timestamp'])
            time_diff = (current_time - extraction_time).total_seconds()
            
            if time_diff > 3600:  # 1 hour
                to_remove.append(extraction_id)
                
                try:
                    output_dir = data['results'].get('output_directory')
                    if output_dir and os.path.exists(output_dir):
                        shutil.rmtree(output_dir)
                except:
                    pass
        
        for extraction_id in to_remove:
            del extraction_results[extraction_id]
        
        return jsonify({'success': True, 'cleaned': len(to_remove)})
        
    except Exception as e:
        print(f"Cleanup error: {e}")
        return jsonify({'error': f'Cleanup error: {str(e)}'}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"Starting Flask app on port {port}")
    app.run(debug=False, host='0.0.0.0', port=port)
