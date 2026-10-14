# ADR-006: Numbers by Reference in Assistant Answers

- **Status:** Proposed
- **Decision:** The LLM never writes metric values. Its final answer is a template that refers to values in tool results, such as `{{c1:rows/meta_furnace_fall/cost_per_qualified_lead}}`. The backend resolves each reference and formats it by metric type (currency, percentage, count). Tools precompute deltas and percentage changes so the LLM never does arithmetic. Unknown references, or bare numerals outside references (other than dates in the resolved period), trigger one retry and then a failed run. Caveats come from tool warning codes and are appended by the backend, not written by the LLM.
- **Context:** The main risk in a conversational analytics assistant is a plausible but invented or miscalculated number. Checking numbers after the fact is fuzzy; inserting them by reference makes fabrication structurally impossible and testable.
- **Consequences:** Every number in an answer traces to a tool call in the run trace. Prompts are a little more complex, and tools must return every value an answer might need, including deltas and ranks. The benchmark measures "ungrounded numbers = 0" directly.
