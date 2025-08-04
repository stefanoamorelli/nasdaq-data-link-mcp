# Contributing to Nasdaq Data Link MCP

Thank you for your interest in contributing to the Nasdaq Data Link MCP Server! This document provides guidelines for contributing to the project.

## Getting Started

### Prerequisites

- Python 3.13+
- uv package manager
- Git

### Development Setup

1. **Clone the repository**
   ```bash
   git clone https://github.com/stefanoamorelli/nasdaq-data-link-mcp.git
   cd nasdaq-data-link-mcp
   ```

2. **Set up development environment**
   ```bash
   uv init mcp
   uv add "mcp[cli]"
   uv add --group test "pytest>=7.0" "pytest-mock" "pytest-cov"
   ```

3. **Configure environment variables**
   ```bash
   cp .env.example .env
   # Add your Nasdaq Data Link API key to .env
   ```

4. **Install the server in development mode**
   ```bash
   uv run mcp install nasdaq_data_link_mcp_os/server.py --env-file .env --name "Nasdaq Data Link MCP Server" --with nasdaq-data-link --with pycountry
   ```

## Development Workflow

### Code Style

- Follow PEP 8 guidelines
- Use meaningful variable names and clear function signatures
- Add docstrings to all public functions and classes
- Keep functions focused and single-purpose

### Testing

- Write tests for all new functionality
- Run tests before submitting changes:
  ```bash
  uv run pytest tests/
  ```
- Aim for good test coverage of critical functionality
- Use mocking for external API calls in tests
- All tests must pass in CI before merge

### Code Quality

- Run linting and formatting:
  ```bash
  uv run ruff check nasdaq_data_link_mcp_os/ tests/
  uv run ruff format nasdaq_data_link_mcp_os/ tests/
  ```
- Run type checking:
  ```bash
  uv run mypy nasdaq_data_link_mcp_os/
  ```

### Documentation

- Update README.md if adding new features
- Update relevant documentation in `docs/` directory
- Include usage examples for new tools
- Update the paper.md if changes affect the research description

## Types of Contributions

### Bug Reports

When filing a bug report, please include:

- Clear description of the issue
- Steps to reproduce the problem
- Expected vs actual behavior
- Python version and environment details
- Relevant error messages or logs

### Feature Requests

For new features, please:

- Describe the use case and motivation
- Explain how it fits with existing functionality
- Consider backward compatibility
- Provide examples of the desired behavior

### Code Contributions

#### Adding New Tools

1. **Create the tool module** in the appropriate resource directory:
   ```
   nasdaq_data_link_mcp_os/resources/[category]/[tool_name].py
   ```

2. **Follow the existing pattern**:
   - Import required dependencies
   - Define tool function with proper type hints
   - Add comprehensive error handling
   - Include docstring with usage examples

3. **Register the tool** in `server.py`:
   ```python
   @server.list_tools()
   async def list_tools() -> list[Tool]:
       return [
           # ... existing tools
           Tool(
               name="your_new_tool",
               description="Clear description of what the tool does",
               inputSchema={
                   "type": "object",
                   "properties": {
                       # Define parameters
                   }
               }
           )
       ]
   ```

4. **Add tests** in `tests/test_tools.py` or create new test file

#### Improving Existing Tools

- Maintain backward compatibility
- Update documentation and examples
- Add tests for new functionality
- Consider edge cases and error handling

## Pull Request Process

1. **Fork the repository** and create a feature branch:
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make your changes** following the guidelines above

3. **Test thoroughly**:
   ```bash
   uv run pytest tests/
   ```

4. **Update documentation** as needed

5. **Commit with clear messages**:
   ```bash
   git commit -m "Add feature: description of what was added"
   ```

6. **Push to your fork** and create a pull request:
   ```bash
   git push origin feature/your-feature-name
   ```

7. **Describe your changes** in the pull request:
   - What was changed and why
   - How to test the changes
   - Any breaking changes or special considerations

## Code Review

All contributions will be reviewed for:

- Code quality and adherence to project standards
- Test coverage and functionality
- Documentation completeness
- Backward compatibility
- Security considerations

## Community Guidelines

- Be respectful and constructive in discussions
- Help others learn and grow
- Focus on the technical merits of contributions
- Acknowledge the work of others

## Getting Help

- Check existing issues for similar problems
- Ask questions in GitHub Discussions
- Reach out to maintainers if needed

## License

By contributing to this project, you agree that your contributions will be licensed under the same MIT License that covers the project.

## Recognition

Contributors will be acknowledged in:
- GitHub contributor list
- Release notes for significant contributions
- README.md for major features

Thank you for helping make financial data more accessible through conversational AI!