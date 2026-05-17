#!/usr/bin/env python3
"""Test simple image embedding to isolate the issue."""

import sys
import os
from pathlib import Path

# Add src to Python path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

try:
    from lxml import etree
    from teipublisher.runtime.docx_output_functions import DocxOutputFunctions
    from docx import Document
    from io import BytesIO
    
    print("Testing simple image embedding...")
    
    # Create a simple test document with just one image
    config = {
        'input_path': str(Path(__file__).parent / 'demo' / 'test_images' / 'test_image.svg'),
        'pmf': DocxOutputFunctions(),
        'parameters': {'input_path': str(Path(__file__).parent / 'demo' / 'test_images' / 'test_image.svg')}
    }
    
    # Create a basic document
    doc = Document()
    
    # Add a simple paragraph with an image sentinel
    sentinel = etree.Element('{http://www.tei-c.org/ns/docx}image-sentinel')
    sentinel.set('url', 'test_image.svg')
    
    # Test the image processing
    pmf = config['pmf']
    pmf._ensure_styles(config)
    
    # Try to create image drawing
    drawing = pmf._create_image_drawing('test_image.svg', None, None, None, doc, doc.element.nsmap, config)
    
    if drawing is not None:
        print("✓ Image drawing created successfully")
        print(f"Drawing element: {etree.tostring(drawing, pretty_print=True)}")
    else:
        print("✗ Failed to create image drawing")
    
    print("Test completed!")

except Exception as e:
    print(f"Test failed with error: {e}")
    import traceback
    traceback.print_exc()
