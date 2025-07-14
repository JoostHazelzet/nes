# Pyntendo

A Nintendo Entertainment System (NES) emulator written in Python and Cython.
* All core components are implemented, including audio, and the most important mappers.
* Performant (runs at 60fps on modern machines)
* Fully headless operation is supported
  * NumPy-based input/output
  * Very limited external dependencies (really just NumPy)
  * See [Headless Demo](Headless%20Demo.ipynb) for a minimal example
* Pure Python/Cython, fully compatible with CPython (>3.6)

Although most games I have tested seem to run without issues, there are still some open issues that would improve
performance and accuracy and probably make some hard to emulate games work or work better.
* Several popular(ish) mappers are not implemented (along with lots of less popular ones)
* Some fine timing is not quite right, which might cause issues in some sensitive games
* This is not a cycle-accurate emulator, so sub-instruction level timing is not correctly emulated, and some parts of
  other systems are not emulated in a cycle-correct way
* See my [devnotes](devnotes.md) for known issues and planned work

I would like to give huge thanks and kudos to everyone who contributed to the amazing [NESDev Wiki](wiki.nesdev.com)
and all the other fantastic sources (most listed in the code), tests and forums for NES emulator development and 6502
progamming.  Without these resources it would have been impossible to develop this emulator.

## Changes by Joost

The original pyntendo code (https://github.com/jameskmurphy/nes/tree/main) is forked. Next I installed this local python package using `$ python -m pip install -e ./nes`. The -e makes it editable. I made changes in `./nes/nes/cycore/system.pxd` (pxd files works in cython like c header files, see https://docs.cython.org/en/latest/src/tutorial/pxd_files.html) and `./nes/nes/cycore/system.pyx` (pxy files are cython source files, see https://cython.readthedocs.io/en/latest/src/userguide/source_files_and_compilation.html). Once changes are made then you need to rerun `$ python -m pip install -e ./nes` which will compile the cython files and uninstall the previous version automatically. You could optionally increase version key in `./nes/setup.py`. Next you must restart the Jupyter notebook to load the updated package.

Added functions to `nes/cycore/system.pyd/pyx`:
-  cpdef object get_snapshot(self)
-  cpdef object set_snapshot(self, object state)
-  cpdef object step_rl(self, int action=?, int run_frames=?)

## Development Environment Setup

This project uses **direnv** for automatic environment management. When you enter the project directory, direnv will automatically:

- Set up Python virtual environment with uv
- Install all required dependencies (NumPy, Pygame, Cython, etc.)
- Configure development shortcuts and aliases
- Set environment variables for optimal development

### Prerequisites

- **Python 3.8+** for modern dependency compatibility
- **uv** for fast Python package management
- **direnv** for environment management
- **PortAudio** for audio support: `brew install portaudio` (macOS)

### Installation

1. **Install direnv** (if not already installed):
   ```bash
   # macOS
   brew install direnv
   
   # Add to your shell profile (.zshrc, .bashrc, etc.)
   eval "$(direnv hook zsh)"  # or bash
   ```

2. **Install uv** (if not already installed):
   ```bash
   # macOS/Linux
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

3. **Install system dependencies**:
   ```bash
   # macOS (for audio support)
   brew install portaudio
   
   # Ubuntu/Debian
   sudo apt-get install portaudio19-dev
   ```

4. **Enter the project directory**:
   ```bash
   cd nes
   direnv allow  # Allow direnv to load environment
   ```

5. **Install development dependencies**:
   ```bash
   install-dev  # Installs all dependencies including Jupyter
   ```

## Development Commands

### Navigation Shortcuts

| Command | Description |
|---------|-------------|
| `root` | Navigate to project root directory |
| `core` | Navigate to main nes core directory |
| `cycore` | Navigate to Cython core implementation |
| `pycore` | Navigate to Pure Python core (legacy) |
| `tests` | Navigate to tests directory |
| `img` | Navigate to screenshot images |
| `palettes` | Navigate to NES color palettes |
| `shader` | Navigate to OpenGL shaders |

### Python Environment

| Command | Description |
|---------|-------------|
| `install` | Install/sync dependencies with uv |
| `install-dev` | Install with development dependencies |
| `install-editable` | Install package in editable mode |
| `python` | Run Python with uv environment |
| `pip` | Use pip within uv environment |

### Cython Development

| Command | Description |
|---------|-------------|
| `build` | Compile Cython extensions |
| `build-dev` | Compile with debug information |
| `clean-build` | Clean all build artifacts |
| `rebuild` | Clean and rebuild everything |

### NES Emulator

| Command | Description |
|---------|-------------|
| `nes` | Run NES emulator with main.py |
| `nes-headless` | Run in headless mode for testing |
| `test-nes` | Run NES-specific tests |

### Jupyter Development

| Command | Description |
|---------|-------------|
| `jupyter` | Access Jupyter command |
| `jupyter-lab` | Start Jupyter Lab |
| `jupyter-notebook` | Start Jupyter Notebook |
| `demo` | Open Headless Demo notebook |

### Development Workflows

| Command | Description |
|---------|-------------|
| `dev` | Start Jupyter Lab (default development) |
| `test` | Run test suite with pytest |
| `test-watch` | Run tests in watch mode |

### Build and Package

| Command | Description |
|---------|-------------|
| `build-wheel` | Build wheel distribution |
| `build-sdist` | Build source distribution |
| `build-all` | Build both wheel and source |

## Environment Variables

The project automatically configures these environment variables:

- **PROJECT_NAME**: `pyntendo`
- **NES_ROOT**: Project root directory
- **NES_CORE_DIR**: Main NES core (`nes/`)
- **CYCORE_DIR**: Cython implementation (`nes/cycore/`)
- **PYCORE_DIR**: Pure Python implementation (`nes/pycore/`)
- **Cython Settings**: Optimized compilation flags
- **NES_SYNC_MODE**: Audio sync mode (1 = SYNC_AUDIO)
- **NES_SCREEN_SCALE**: Display scaling (3x)

## Quick Start

### Development Mode

1. **Start Jupyter development environment**:
   ```bash
   dev  # Opens Jupyter Lab for interactive development
   ```

2. **Work with the Headless Demo**:
   ```bash
   demo  # Opens the Headless Demo notebook
   ```

3. **Build and test Cython extensions**:
   ```bash
   rebuild  # Clean and rebuild Cython code
   test     # Run tests to verify functionality
   ```

### Running the Emulator

1. **Basic emulation**:
   ```bash
   nes path/to/rom.nes  # Run with GUI
   ```

2. **Headless operation** (for RL/automation):
   ```bash
   nes-headless  # Programmatic control
   ```

3. **Custom configuration**:
   ```bash
   python -c "from nes import NES; nes = NES('rom.nes', screen_scale=4, sync_mode=2)"
   ```

## Development Workflow

### Cython Development Cycle

1. **Edit Cython files** in `nes/cycore/`:
   ```bash
   cycore               # Navigate to Cython source
   # Edit .pyx files
   ```

2. **Rebuild and test**:
   ```bash
   rebuild              # Compile Cython extensions
   test-nes             # Run NES-specific tests
   ```

3. **Interactive testing**:
   ```bash
   demo                 # Use Headless Demo notebook
   ```

### Adding New Features

1. **Implement in Cython**: Add to `nes/cycore/system.pyx`
2. **Update headers**: Modify `nes/cycore/system.pxd`
3. **Rebuild**: Run `rebuild` command
4. **Test**: Use `demo` notebook or `test-nes`
5. **Document**: Update docstrings and README

### Performance Optimization

1. **Profile performance**:
   ```bash
   python -c "import cProfile; cProfile.run('from nes import NES; nes = NES(\"rom.nes\"); nes.run()')"
   ```

2. **Cython optimization**: Use compilation flags in environment
3. **Memory profiling**: Use Jupyter notebooks for analysis

## Project Structure

```
nes/
├── nes/                        # Main package
│   ├── cycore/                 # High-performance Cython implementation
│   │   ├── system.pyx         # Core emulator system
│   │   ├── system.pxd         # Cython header definitions
│   │   └── *.pyx              # Other Cython modules
│   ├── pycore/                 # Pure Python reference implementation
│   │   └── system.py          # Python emulator (slow, for reference)
│   ├── instructions.py        # 6502 instruction definitions
│   ├── peripherals.py         # Input/output handling
│   ├── rom.py                  # ROM loading and parsing
│   └── utils.py                # Utility functions
├── tests/                      # Test suite
├── img/                        # Screenshots and demo images
├── palettes/                   # NES color palette files
├── shader/                     # OpenGL shader files
├── main.py                     # CLI entry point
├── Headless Demo.ipynb         # Interactive demo notebook
├── setup.py                    # Build configuration
├── pyproject.toml              # Modern Python project config
└── .envrc                      # direnv configuration
```

## Custom Modifications (by Joost)

This fork includes additional functionality for machine learning applications:

### Enhanced System Interface

**Added functions** to `nes/cycore/system.pyx`:
- `cpdef object get_snapshot(self)` - Capture complete emulator state
- `cpdef object set_snapshot(self, object state)` - Restore emulator state  
- `cpdef object step_rl(self, int action=?, int run_frames=?)` - RL environment step

### Development Process for Cython Changes

1. **Edit Cython files**: Modify `.pyx` and `.pxd` files
2. **Rebuild**: Run `rebuild` to recompile extensions
3. **Restart Jupyter**: Kernel restart required to load new extensions
4. **Test**: Verify functionality in notebooks or tests

### Installation of Modified Package

```bash
install-editable  # Install package in development mode
# Makes changes immediately available without reinstall
```

The direnv environment handles the complete development lifecycle automatically! 🎮🐍⚡