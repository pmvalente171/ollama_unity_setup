# Goals

The goals for this project are to create a basic setup using flask and ollama to connect an LLM agent to Unity. I want to be able to:

1. Have tools that can manipulate the unity environment (send messages, create new objects, manipulate them, move objects, draw line renderers, etc). I should be able to setup multiple tools both in Unity (each corresponding to a event) and in the server.
2. Have more than one agent instanced at the same time, each with different tools and system prompts.

The end goal for this project is **to have a multi-agent system that I can give instructions to a main agent, and it creates a swarm of 5 builders that accomplish the requested changes.** 


# Server Requirements

I need the following:

1. A endpoint to add a new agent.
2. A endpoint to give an instruction to an agent (`plan_and_execute`).
3. Setup communication tools such that the agents could talk to each other.

# Client Requirements

1. have a main agent that I can prompt to create a building, the agent acts a coordinator creating new builder agents that engage in building a request.
2. the agents need to be able to coordenate together, possibly through voting system.
3. the setup should be done mostly through code.

# Technology

1. Use flask to create the server.
2. The server needs to be really simple, this is an example project for students.
3. Use ollama for using/communicating with the LLMs.
4. Use a Qwen3-8b for the LLMs.