# Claude Code + Ollama Demo

Demo code for the blog post: [How to Use Claude Code with Open Source Models (Completely Free)](https://www.srcecde.me/posts/claude-code-ollama-open-source-free/)

The blog covers setup, model selection, context window configuration, hardware requirements, testing results, and troubleshooting.

## What's in this repo

### `buggy_shopping_cart.py`

A shopping cart with three intentional bugs used in the blog's practical demonstration — duplicate item creation, list mutation during iteration, and silent acceptance of invalid discount codes. This is what Claude Code (running via Ollama) is asked to find and fix.

### `test_project/`

A multi-file e-commerce platform (~2,400 lines across 5 Python files) used to test context window behavior across different sizes (16K, 32K, 64K). The blog walks through 10 sequential prompts that evaluate multi-file reading, cross-file comparison, code generation, and complex flow tracing.

```
test_project/
├── models.py       # Data models (Product, Customer, Order, etc.)
├── database.py     # In-memory database with connection pooling
├── services.py     # Business logic layer
├── routes.py       # REST API endpoint definitions
└── utils.py        # Validation, formatting, hashing utilities
```
