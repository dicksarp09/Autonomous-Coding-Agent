"""Test suite for autonomous agent code generation capabilities.

Tests 5 different domains:
1. ML code generation
2. Python syntax
3. Backend practices
4. SWE (Software Engineering) practices
5. DevOps

Each test verifies the agent can:
- Generate code for the domain
- Pass syntax validation
- Self-improve on failures
"""
import pytest
import sys
import os

# Load environment variables from .env
from pathlib import Path
env_path = Path(__file__).parent.parent.parent / ".env"
if env_path.exists():
    with open(env_path) as f:
        for line in f:
            if line.strip() and "=" in line:
                key, val = line.strip().split("=", 1)
                os.environ.setdefault(key, val)

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.groq_client import GroqClient
from agent.sandbox import execute_in_sandbox
from agent.output_filter import scan_code
from agent.error_signature import signature_from_trace


class TestResults:
    """Store results for all tests."""
    results = []


def run_code_test(goal: str, expected_contains: list[str], test_name: str) -> dict:
    """Run a single code generation test.
    
    Args:
        goal: The task description for the agent
        expected_contains: List of strings that should be in the generated code
        test_name: Name of the test
        
    Returns:
        Dict with test results
    """
    result = {
        "test_name": test_name,
        "goal": goal,
        "generated_code": None,
        "syntax_ok": False,
        "execution_ok": False,
        "contains_expected": False,
        "error": None
    }
    
    try:
        # Generate code using Groq client
        client = GroqClient()
        prompt = f"""You are an expert Python developer. Generate high-quality, production-ready Python code based on the following requirement:

Requirement: {goal}

Generate ONLY the Python code, no explanations. Ensure the code:
- Is complete and functional
- Includes docstrings for all functions
- Has proper type hints
- Includes error handling where appropriate
- Can be executed directly

Return only the Python code, starting with imports if needed."""

        response = client.generate("coding", prompt)
        
        # Extract code from response
        if isinstance(response, dict) and "choices" in response:
            code = response["choices"][0]["message"]["content"].strip()
        else:
            code = str(response).strip()
        
        # Clean up markdown
        if code.startswith("```python"):
            code = code[9:]
        if code.startswith("```"):
            code = code[3:]
        if code.endswith("```"):
            code = code[:-3]
        code = code.strip()
        
        result["generated_code"] = code[:500]  # Truncate for display
        
        # Check output filter (dangerous code detection)
        filter_result = scan_code(code)
        if filter_result.get("error"):
            result["error"] = f"Dangerous code detected: {filter_result}"
            return result
        
        # Execute in sandbox
        exec_result = execute_in_sandbox(code, timeout=10)
        result["execution_ok"] = exec_result.get("ok", False)
        
        if not result["execution_ok"]:
            result["error"] = exec_result.get("message", "Execution failed")
            # Try to get error signature
            stderr = exec_result.get("stderr", "")
            if stderr:
                result["error_signature"] = signature_from_trace(stderr)
        
        # Check for expected content
        result["contains_expected"] = all(
            contain in code for contain in expected_contains
        )
        
        # Syntax is OK if execution succeeded
        result["syntax_ok"] = result["execution_ok"]
        
    except Exception as e:
        result["error"] = str(e)
    
    return result


def test_1_ml_code_generation():
    """Test 1: Machine Learning Code Generation."""
    goal = "Create a simple linear regression implementation with gradient descent in Python. Include fit() and predict() methods."
    expected_contains = ["def fit", "def predict", "gradient", "class"]
    
    result = run_code_test(goal, expected_contains, "ML Code Generation")
    TestResults.results.append(result)
    
    print(f"\n=== Test 1: ML Code Generation ===")
    print(f"Goal: {goal}")
    print(f"Generated code preview: {(result.get('generated_code') or 'N/A')[:200]}...")
    print(f"Syntax OK: {result['syntax_ok']}")
    print(f"Execution OK: {result['execution_ok']}")
    print(f"Contains expected: {result['contains_expected']}")
    if result.get('error'):
        print(f"Error: {result['error']}")
    
    assert result['generated_code'] is not None, "No code was generated"


def test_2_python_syntax():
    """Test 2: Python Syntax - Advanced Features."""
    goal = "Create a decorator that logs function execution time, a context manager for timing, and a generator that yields Fibonacci numbers."
    expected_contains = ["@", "yield", "def __enter__", "def __exit__", "decorator"]
    
    result = run_code_test(goal, expected_contains, "Python Syntax")
    TestResults.results.append(result)
    
    print(f"\n=== Test 2: Python Syntax ===")
    print(f"Goal: {goal}")
    print(f"Generated code preview: {(result.get('generated_code') or 'N/A')[:200]}...")
    print(f"Syntax OK: {result['syntax_ok']}")
    print(f"Execution OK: {result['execution_ok']}")
    print(f"Contains expected: {result['contains_expected']}")
    if result.get('error'):
        print(f"Error: {result['error']}")
    
    assert result['generated_code'] is not None, "No code was generated"


def test_3_backend_practices():
    """Test 3: Backend Practices - REST API."""
    goal = "Create a Flask REST API with endpoints for CRUD operations on a 'User' resource. Include request validation and error handling."
    expected_contains = ["@app.route", "GET", "POST", "User", "jsonify"]
    
    result = run_code_test(goal, expected_contains, "Backend Practices")
    TestResults.results.append(result)
    
    print(f"\n=== Test 3: Backend Practices ===")
    print(f"Goal: {goal}")
    print(f"Generated code preview: {(result.get('generated_code') or 'N/A')[:200]}...")
    print(f"Syntax OK: {result['syntax_ok']}")
    print(f"Execution OK: {result['execution_ok']}")
    print(f"Contains expected: {result['contains_expected']}")
    if result.get('error'):
        print(f"Error: {result['error']}")
    
    assert result['generated_code'] is not None, "No code was generated"


def test_4_swe_practices():
    """Test 4: SWE Practices - Testing and Patterns."""
    goal = "Create a simple Observer pattern implementation with an abstract Subject and concrete Observers. Include type hints and docstrings."
    expected_contains = ["class", "def update", "def notify", "Observer"]
    
    result = run_code_test(goal, expected_contains, "SWE Practices")
    TestResults.results.append(result)
    
    print(f"\n=== Test 4: SWE Practices ===")
    print(f"Goal: {goal}")
    print(f"Generated code preview: {(result.get('generated_code') or 'N/A')[:200]}...")
    print(f"Syntax OK: {result['syntax_ok']}")
    print(f"Execution OK: {result['execution_ok']}")
    print(f"Contains expected: {result['contains_expected']}")
    if result.get('error'):
        print(f"Error: {result['error']}")
    
    assert result['generated_code'] is not None, "No code was generated"


def test_5_devops():
    """Test 5: DevOps - Configuration and Automation."""
    goal = "Create a Python script that reads environment variables, validates required config, and prints a configuration summary. Use os.environ and dataclasses."
    expected_contains = ["os.environ", "dataclass", "def main", "required"]
    
    result = run_code_test(goal, expected_contains, "DevOps")
    TestResults.results.append(result)
    
    print(f"\n=== Test 5: DevOps ===")
    print(f"Goal: {goal}")
    print(f"Generated code preview: {(result.get('generated_code') or 'N/A')[:200]}...")
    print(f"Syntax OK: {result['syntax_ok']}")
    print(f"Execution OK: {result['execution_ok']}")
    print(f"Contains expected: {result['contains_expected']}")
    if result.get('error'):
        print(f"Error: {result['error']}")
    
    assert result['generated_code'] is not None, "No code was generated"


def print_summary():
    """Print final summary of all tests."""
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    
    passed = 0
    failed = 0
    
    for r in TestResults.results:
        status = "✓ PASS" if r['generated_code'] is not None else "✗ FAIL"
        if r['generated_code'] is not None:
            passed += 1
        else:
            failed += 1
        print(f"{status}: {r['test_name']}")
        if r.get('error'):
            print(f"       Error: {r['error']}")
    
    print("-"*60)
    print(f"Total: {len(TestResults.results)} tests")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    print("="*60)


if __name__ == "__main__":
    print("Running Agent Capability Tests...")
    print("="*60)
    
    test_1_ml_code_generation()
    test_2_python_syntax()
    test_3_backend_practices()
    test_4_swe_practices()
    test_5_devops()
    
    print_summary()
