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
        # Try to render template, fallback to inline HTML if template missing
        return render_template('index.html')
    except Exception as e:
        print(f"Template error: {e}, using fallback HTML")
        return """
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>PDF Table Extractor</title>
            <style>
                * { margin: 0; padding: 0; box-sizing: border-box; }
                body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); min-height: 100vh; padding: 20px; }
                .container { max-width: 800px; margin: 0 auto; background: rgba(255, 255, 255, 0.95); border-radius: 20px; padding: 40px; box-shadow: 0 20px 40px rgba(0, 0, 0, 0.1); }
                .header { text-align: center; margin-bottom: 40px; }
                .header h1 { color: #333; font-size: 2.5em; margin-bottom: 10px; }
                .form-group { margin-bottom: 25px; }
                .form-group label { display: block; margin-bottom: 8px; font-weight: 600; color: #333; }
                .form-control { width: 100%; padding: 15px; border: 2px solid #e1e5e9; border-radius: 10px; font-size: 1em; transition: all 0.3s ease; }
                .form-control:focus { outline: none; border-color: #667eea; box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1); }
                .btn { background: linear-gradient(45deg, #667eea, #764ba2); color: white; border: none; padding: 15px 30px; border-radius: 25px; font-size: 1.1em; font-weight: 600; cursor: pointer; transition: all 0.3s ease; width: 100%; }
                .btn:hover { transform: translateY(-2px); box-shadow: 0 10px 20px rgba(102, 126, 234, 0.3); }
                .btn:disabled { opacity: 0.6; cursor: not-allowed; transform: none; }
                .alert { padding: 15px; border-radius: 10px; margin: 20px 0; display: none; }
                .alert-success { background: #d4edda; color: #155724; border: 1px solid #c3e6cb; }
                .alert-danger { background: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; }
                .loading { text-align: center; margin: 20px 0; display: none; }
                .spinner { border: 3px solid #f3f3f3; border-top: 3px solid #667eea; border-radius: 50%; width: 40px; height: 40px; animation: spin 1s linear infinite; margin: 0 auto 15px; }
                @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
                .results { margin-top: 30px; display: none; }
                .results h3 { color: #333; margin-bottom: 20px; }
                .table-item { background: #f8f9fa; padding: 15px; border-radius: 10px; margin-bottom: 15px; border-left: 4px solid #667eea; }
                .download-btn { background: #28a745; color: white; padding: 8px 16px; border: none; border-radius: 5px; text-decoration: none; display: inline-block; margin: 5px; font-size: 0.9em; }
                .download-btn:hover { background: #218838; }
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>📊 PDF Table Extractor</h1>
                    <p>Extract tables from PDF files using AI</p>
                </div>

                <form id="uploadForm" enctype="multipart/form-data">
                    <div class="form-group">
                        <label for="api_key">Google AI API Key:</label>
                        <input type="password" id="api_key" name="api_key" class="form-control" 
                               placeholder="Enter your Google AI API key" required>
                        <small style="color: #666; font-size: 0.9em;">
                            Get your API key from <a href="https://makersuite.google.com/app/apikey" target="_blank">Google AI Studio</a>
                        </small>
                    </div>

                    <div class="form-group">
                        <label for="file">PDF File:</label>
                        <input type="file" id="file" name="file" class="form-control" 
                               accept=".pdf" required>
                    </div>

                    <button type="submit" id="submitBtn" class="btn">
                        Extract Tables
                    </button>
                </form>

                <div id="loading" class="loading">
                    <div class="spinner"></div>
                    <p>Processing PDF... This may take a few minutes.</p>
                </div>

                <div id="error" class="alert alert-danger"></div>
                <div id="success" class="alert alert-success"></div>

                <div id="results" class="results">
                    <h3>📋 Extraction Results</h3>
                    <div id="resultsContent"></div>
                </div>
            </div>

            <script>
                let currentExtractionId = null;

                document.getElementById('uploadForm').addEventListener('submit', async function(e) {
                    e.preventDefault();
                    
                    const formData = new FormData(this);
                    const submitBtn = document.getElementById('submitBtn');
                    const loading = document.getElementById('loading');
                    const error = document.getElementById('error');
                    const success = document.getElementById('success');
                    const results = document.getElementById('results');
                    
                    error.style.display = 'none';
                    success.style.display = 'none';
                    results.style.display = 'none';
                    
                    submitBtn.disabled = true;
                    loading.style.display = 'block';
                    
                    try {
                        const response = await fetch('/upload', {
                            method: 'POST',
                            body: formData
                        });
                        
                        if (!response.ok) {
                            throw new Error(`Server error: ${response.status}`);
                        }
                        
                        const responseText = await response.text();
                        if (!responseText.trim()) {
                            throw new Error('Empty response from server');
                        }
                        
                        const data = JSON.parse(responseText);
                        
                        if (data.success) {
                            currentExtractionId = data.extraction_id;
                            displayResults(data.results);
                            success.innerHTML = '✅ PDF processed successfully!';
                            success.style.display = 'block';
                        } else {
                            throw new Error(data.error || 'Unknown error');
                        }
                    } catch (err) {
                        console.error('Error:', err);
                        error.innerHTML = `❌ Error: ${err.message}`;
                        error.style.display = 'block';
                    } finally {
                        submitBtn.disabled = false;
                        loading.style.display = 'none';
                    }
                });

                function displayResults(results) {
                    const resultsContent = document.getElementById('resultsContent');
                    const resultsDiv = document.getElementById('results');
                    
                    let html = `
                        <div class="table-item">
                            <h4>📄 ${results.pdf_name}</h4>
                            <p><strong>Total Pages:</strong> ${results.total_pages}</p>
                            <p><strong>Pages with Tables:</strong> ${results.pages_with_tables}</p>
                            <p><strong>Tables Extracted:</strong> ${results.total_tables_extracted}</p>
                        </div>
                    `;
                    
                    if (results.csv_files && results.csv_files.length > 0) {
                        html += '<div class="table-item"><h4>📥 Download Files</h4>';
                        
                        results.csv_files.forEach(filename => {
                            html += `<a href="/download_csv/${currentExtractionId}/${filename}" class="download-btn">📄 ${filename}</a>`;
                        });
                        
                        html += `<br><br><a href="/download/${currentExtractionId}" class="download-btn" style="background: #007bff;">📦 Download All (ZIP)</a>`;
                        html += '</div>';
                    }
                    
                    resultsContent.innerHTML = html;
                    resultsDiv.style.display = 'block';
                }
            </script>
        </body>
        </html>
        """

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
        
        if 'file' not in request.files:
            return jsonify({'error': 'No file selected'}), 400
        
        file = request.files['file']
        api_key = request.form.get('api_key', '').strip()
        
        if not file or file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        if not api_key:
            return jsonify({'error': 'Google AI API key is required'}), 400
        
        if not file.filename.lower().endswith('.pdf'):
            return jsonify({'error': 'Please upload a PDF file'}), 400
        
        # Test imports
        try:
            import google.generativeai as genai
            from pdf_extractor import PDFTableExtractor
        except ImportError as e:
            return jsonify({'error': f'Missing dependency: {str(e)}'}), 500
        
        # Test API key
        try:
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel('gemini-2.0-flash-exp')
        except Exception as e:
            return jsonify({'error': f'Invalid API key: {str(e)}'}), 400
        
        # Process file
        extraction_id = str(uuid.uuid4())
        filename = secure_filename(file.filename)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        unique_filename = f"{timestamp}_{filename}"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
        
        file.save(filepath)
        
        try:
            extractor = PDFTableExtractor(api_key)
            results = extractor.process_pdf(filepath)
            
            if "error" in results:
                return jsonify({'error': f'Processing error: {results["error"]}'}), 500
            
            extraction_results[extraction_id] = {
                'results': results,
                'filepath': filepath,
                'extractor': extractor,
                'timestamp': datetime.now().isoformat()
            }
            
            # Clean up
            try:
                os.remove(filepath)
            except:
                pass
            
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
            
            return jsonify(response_data)
            
        except Exception as e:
            try:
                os.remove(filepath)
            except:
                pass
            return jsonify({'error': f'Processing error: {str(e)}'}), 500
        
    except Exception as e:
        print(f"Upload error: {e}")
        traceback.print_exc()
        return jsonify({'error': f'Server error: {str(e)}'}), 500

@app.route('/download/<extraction_id>')
def download_results(extraction_id):
    """Download all CSV files as ZIP"""
    try:
        if extraction_id not in extraction_results:
            return jsonify({'error': 'Results not found'}), 404
        
        extraction_data = extraction_results[extraction_id]
        results = extraction_data['results']
        
        if not results.get('csv_files'):
            return jsonify({'error': 'No files available'}), 404
        
        temp_dir = tempfile.mkdtemp()
        zip_filename = f"{results['pdf_name']}_tables.zip"
        zip_path = os.path.join(temp_dir, zip_filename)
        
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for csv_file in results['csv_files']:
                if os.path.exists(csv_file):
                    zipf.write(csv_file, os.path.basename(csv_file))
        
        return send_file(zip_path, as_attachment=True, download_name=zip_filename)
        
    except Exception as e:
        return jsonify({'error': f'Download error: {str(e)}'}), 500

@app.route('/download_csv/<extraction_id>/<filename>')
def download_single_csv(extraction_id, filename):
    """Download single CSV file"""
    try:
        if extraction_id not in extraction_results:
            return jsonify({'error': 'Results not found'}), 404
        
        extraction_data = extraction_results[extraction_id]
        results = extraction_data['results']
        
        for csv_file in results.get('csv_files', []):
            if os.path.basename(csv_file) == filename and os.path.exists(csv_file):
                return send_file(csv_file, as_attachment=True, download_name=filename)
        
        return jsonify({'error': 'File not found'}), 404
        
    except Exception as e:
        return jsonify({'error': f'Download error: {str(e)}'}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"Starting Flask app on port {port}")
    app.run(debug=False, host='0.0.0.0', port=port)
