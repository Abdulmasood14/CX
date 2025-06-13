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

# Import your existing PDFTableExtractor class
from pdf_extractor import PDFTableExtractor

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
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    """Handle PDF file upload and extraction"""
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file selected'}), 400
        
        file = request.files['file']
        api_key = request.form.get('api_key', '').strip()
        
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        if not api_key:
            return jsonify({'error': 'Google AI API key is required'}), 400
        
        if file and file.filename.lower().endswith('.pdf'):
            # Generate unique ID for this extraction
            extraction_id = str(uuid.uuid4())
            
            # Save uploaded file
            filename = secure_filename(file.filename)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            unique_filename = f"{timestamp}_{filename}"
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
            file.save(filepath)
            
            try:
                # Initialize extractor with provided API key
                extractor = PDFTableExtractor(api_key)
                
                # Process PDF
                results = extractor.process_pdf(filepath)
                
                # Store results with extraction ID
                extraction_results[extraction_id] = {
                    'results': results,
                    'filepath': filepath,
                    'extractor': extractor,
                    'timestamp': datetime.now().isoformat()
                }
                
                # Clean up uploaded file after processing
                try:
                    os.remove(filepath)
                except:
                    pass
                
                # Return success response with extraction ID
                return jsonify({
                    'success': True,
                    'extraction_id': extraction_id,
                    'results': {
                        'pdf_name': results['pdf_name'],
                        'total_pages': results['total_pages'],
                        'pages_with_tables': results['pages_with_tables'],
                        'total_tables_extracted': results['total_tables_extracted'],
                        'extracted_titles': results.get('extracted_titles', []),
                        'csv_files': [os.path.basename(f) for f in results['csv_files']]
                    }
                })
                
            except Exception as e:
                # Clean up uploaded file on error
                try:
                    os.remove(filepath)
                except:
                    pass
                return jsonify({'error': f'Processing error: {str(e)}'}), 500
        
        return jsonify({'error': 'Please upload a PDF file'}), 400
        
    except Exception as e:
        return jsonify({'error': f'Upload error: {str(e)}'}), 500

@app.route('/download/<extraction_id>')
def download_results(extraction_id):
    """Download all CSV files as a ZIP archive"""
    try:
        if extraction_id not in extraction_results:
            return jsonify({'error': 'Extraction results not found'}), 404
        
        extraction_data = extraction_results[extraction_id]
        results = extraction_data['results']
        
        if not results['csv_files']:
            return jsonify({'error': 'No CSV files available for download'}), 404
        
        # Create temporary ZIP file
        temp_dir = tempfile.mkdtemp()
        zip_filename = f"{results['pdf_name']}_extracted_tables.zip"
        zip_path = os.path.join(temp_dir, zip_filename)
        
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for csv_file in results['csv_files']:
                if os.path.exists(csv_file):
                    # Add file to ZIP with just the filename (not full path)
                    arcname = os.path.basename(csv_file)
                    zipf.write(csv_file, arcname)
        
        # Send file and clean up
        def remove_temp_dir():
            try:
                shutil.rmtree(temp_dir)
            except:
                pass
        
        return send_file(
            zip_path,
            as_attachment=True,
            download_name=zip_filename,
            mimetype='application/zip'
        )
        
    except Exception as e:
        return jsonify({'error': f'Download error: {str(e)}'}), 500

@app.route('/download_csv/<extraction_id>/<filename>')
def download_single_csv(extraction_id, filename):
    """Download a single CSV file"""
    try:
        if extraction_id not in extraction_results:
            return jsonify({'error': 'Extraction results not found'}), 404
        
        extraction_data = extraction_results[extraction_id]
        results = extraction_data['results']
        
        # Find the requested CSV file
        for csv_file in results['csv_files']:
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
                'pdf_name': results['pdf_name'],
                'total_pages': results['total_pages'],
                'pages_with_tables': results['pages_with_tables'],
                'total_tables_extracted': results['total_tables_extracted'],
                'extracted_titles': results.get('extracted_titles', []),
                'csv_files': [os.path.basename(f) for f in results['csv_files']],
                'timestamp': extraction_data['timestamp']
            }
        })
        
    except Exception as e:
        return jsonify({'error': f'Status error: {str(e)}'}), 500

@app.route('/cleanup')
def cleanup_old_results():
    """Clean up old extraction results (older than 1 hour)"""
    try:
        current_time = datetime.now()
        to_remove = []
        
        for extraction_id, data in extraction_results.items():
            extraction_time = datetime.fromisoformat(data['timestamp'])
            time_diff = (current_time - extraction_time).total_seconds()
            
            # Remove results older than 1 hour
            if time_diff > 3600:
                to_remove.append(extraction_id)
                
                # Clean up files
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
        return jsonify({'error': f'Cleanup error: {str(e)}'}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)