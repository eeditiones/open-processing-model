#!/usr/bin/env python3
"""Simple test script to verify image embedding functionality."""

import sys
import os
from pathlib import Path

# Add src to Python path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

try:
    from lxml import etree
    from teipublisher.runtime.docx_output_functions import DocxOutputFunctions
    import tempfile
    import zipfile
    from io import BytesIO
    
    print("Testing image embedding functionality...")
    
    # Create a simple test config
    config = {
        'input_path': str(Path(__file__).parent / 'tests' / 'test-docx.xml'),
        'pmf': DocxOutputFunctions(),
        'parameters': {'input_path': str(Path(__file__).parent / 'tests' / 'test-docx.xml')}
    }
    
    # Parse the test document
    test_xml_path = Path(__file__).parent / 'tests' / 'test-docx.xml'
    tree = etree.parse(str(test_xml_path))
    root = tree.getroot()
    
    # Find the graphic element
    graphic = root.find('.//{*}graphic')
    if graphic is not None:
        print(f"✓ Found graphic element: {graphic.get('corresp')}")
        
        # Test the graphic function
        result = config['pmf'].graphic(config, graphic, [], None)
        print(f"✓ Graphic function returned: {len(result)} elements")
        
        if result and len(result) > 0:
            sentinel = result[0]
            if hasattr(sentinel, 'tag') and 'image-sentinel' in sentinel.tag:
                print("✓ Image sentinel created successfully")
                print(f"  - URL: {sentinel.get('url')}")
            else:
                print("✗ No image sentinel found")
        else:
            print("✗ No result from graphic function")
    else:
        print("✗ No graphic element found in test XML")
    
    # Test the full transform process
    print("\nTesting full transform process...")
    
    # Create a minimal transform module for testing
    test_module_content = '''
from lxml import etree
from teipublisher.runtime.docx_output_functions import DocxOutputFunctions, docx_apply_children

def transform(root, runtime_options=None):
    config = {
        'pmf': DocxOutputFunctions(),
        'apply_children': docx_apply_children,
        'dispatch': _dispatch,
        'parameters': runtime_options or {},
        'normalize_text': None,
        'odd_css': '',
        'footnotes': [],
    }
    
    if runtime_options and 'docx_template' in runtime_options:
        config['docx_template'] = runtime_options['docx_template']
    
    result = apply(config, [root])
    result = config['pmf'].finish(config, result)
    return result

def apply(config, nodes):
    return _apply_impl(config, nodes, config['dispatch'])

def _apply_impl(config, nodes, dispatch):
    result = []
    for node in nodes:
        if isinstance(node, str):
            result.append(node)
        elif hasattr(node, 'tag'):
            result.extend(dispatch(config, node, {}))
    return result

def _dispatch(config, node, params):
    tag = etree.QName(node.tag).localname
    if tag == 'graphic':
        return config['pmf'].graphic(config, node, [], None)
    elif tag == 'p':
        return config['pmf'].paragraph(config, node, [], None)
    elif tag == 'figure':
        return config['pmf'].figure(config, node, [], None)
    elif tag == 'head':
        return config['pmf'].heading(config, node, [], None, level=1)
    elif tag == 'body':
        return config['pmf'].body(config, node, [], None)
    elif tag == 'text':
        return config['pmf'].text(config, node, [], None)
    else:
        return config['pmf'].pass_through(config, node, [], None)

def transform_output_channels():
    return ['docx']
'''
    
    # Write the test module to a temporary file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        f.write(test_module_content)
        test_module_path = f.name
    
    try:
        # Import the test module
        import importlib.util
        spec = importlib.util.spec_from_file_location("test_module", test_module_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Could not load module from {test_module_path}")
        test_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(test_module)
        
        # Run the transform
        result = test_module.transform(root, {'input_path': str(test_xml_path)})
        
        if isinstance(result, bytes):
            print("✓ Transform returned bytes (DOCX data)")
            
            # Check if it's a valid ZIP/DOCX file
            try:
                with zipfile.ZipFile(BytesIO(result)) as z:
                    file_list = z.namelist()
                    print(f"✓ Valid DOCX file with {len(file_list)} files")
                    
                    # Check for image files
                    image_files = [f for f in file_list if f.startswith('word/media/')]
                    if image_files:
                        print(f"✓ Found {len(image_files)} image files: {image_files}")
                    else:
                        print("✗ No image files found in DOCX")
                    
                    # Check for drawing elements
                    if 'word/document.xml' in file_list:
                        doc_xml = z.read('word/document.xml')
                        doc_root = etree.fromstring(doc_xml)
                        # Use xpath instead of iter for better type compatibility
                        drawings = doc_root.xpath('//w:drawing', namespaces={'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'})
                        if drawings:
                            print(f"✓ Found {len(drawings)} drawing elements in document.xml")
                        else:
                            print("✗ No drawing elements found in document.xml")
                    
                    # Check for relationships
                    if 'word/_rels/document.xml.rels' in file_list:
                        rels_xml = z.read('word/_rels/document.xml.rels')
                        rels_root = etree.fromstring(rels_xml)
                        image_rels = rels_root.xpath("//ns:Relationship[@Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/image']", 
                                                   namespaces={'ns': 'http://schemas.openxmlformats.org/package/2006/relationships'})
                        if image_rels:
                            print(f"✓ Found {len(image_rels)} image relationships")
                        else:
                            print("✗ No image relationships found")
                    
            except Exception as e:
                print(f"✗ Invalid DOCX file: {e}")
        else:
            print(f"✗ Transform returned unexpected type: {type(result)}")
    
    finally:
        # Clean up temporary module
        os.unlink(test_module_path)
    
    print("\nTest completed!")

except ImportError as e:
    print(f"Import error: {e}")
    print("Required dependencies not available for testing")
except Exception as e:
    print(f"Test failed with error: {e}")
    import traceback
    traceback.print_exc()
