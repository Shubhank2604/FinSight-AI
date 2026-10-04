# Dependency and runtime contract

The verified runtime is CPython 3.13.9 on Windows x64. CI targets Python 3.13 on Linux. Earlier README claims of Python 3.11+ are withdrawn: the new resolved NumPy/Pandas versions have newer minimum versions. A configured CI matrix is not proof that CI has executed on GitHub; no remote CI result is claimed for this local branch.

`requirements.txt` lists direct requirements; `requirements.lock` pins 77 direct and transitive distributions from the OpenAI verification environment. Windows-only pywin32 has a platform marker. Install the lock for reproducibility. This is a version lock, not a hash-verified supply-chain lock. The environment is checked with `pip check` and the application tests in a fresh venv. Unrelated packages from the personal development environment are not included.

The obsolete py_vollib/Numba dependency path was replaced with explicit closed-form Black-Scholess using Python's normal CDF. Tests use a reference call value and put-call parity. No GPU, Torch, large local model, SciPy or local semantic transformer download is required. Hash embeddings are the CPU regression baseline; Optional OpenAI or Gemini semantic embeddings require a network and quota.

In restricted Windows environments, pytest's shared system temporary directory may be unreadable. Create `.test-tmp` first, then use a fresh workspace-owned test directory: `python -m pytest -q -p no:cacheprovider --basetemp=.test-tmp/check-1`. This directory is ignored by Git. Changing temp/cache paths fixes environment access errors; it does not excuse failed assertions.

The default lock now includes the official `openai==3.13.0` SDK and its `httpx2` transport. Google generation/auth dependencies were removed from the default runtime. `requirements-embeddings.txt` retains `google-genai==1.74.0` only for existing Gemini embedding indexes; its import is lazy. Install that file only when explicitly retaining `EMBEDDING_PROVIDER=gemini`. The generation adapter never imports Google libraries.
