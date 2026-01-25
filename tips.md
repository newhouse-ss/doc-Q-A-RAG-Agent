## models.py
- the temperature parameter: control the randomness and creativity of the model, temperature==0, model will choose the option with highest probability, when temperature is high, the output would be more diverse and easier to hallucination.
- the max_retries parameter: when unsuccessfully call the API, max chances able to try again.  
## graph_builder.py
- StateGraph: used to define the work streaming
- START, END: sign the start and end
- MessageState: dictionary, save the messages history
- ToolNode: run the tools
- tools_condition: judge whether the llm request to cal  the tool.

CI/CD??