Overview

DocTalk Gen AI (GitHub) is an AI-powered document chat application designed to allow users to upload PDF files, process their content, and ask questions about the documents. It leverages a conversational AI model (LLaMA 3.2) with Elasticsearch for vector-based document retrieval, providing efficient and context-aware responses. The application uses Streamlit for an intuitive web-based interface.

 Purpose

 The application enables users to interact with PDF documents conversationally, extracting insights and answering queries based on the document content. It is ideal for users who need to quickly understand or query large documents without manually searching through them.

 Features

PDF Upload: Upload PDF files for processing.

Text Extraction and Indexing: Extracts text from PDFs, splits it into chunks, generates embeddings, and indexes them in Elasticsearch.

Conversational AI: Uses LLaMA 3.2 to answer questions with context from the uploaded PDFs.

Chat History: Maintains a conversation history for context-aware interactions.

Source Attribution: Displays the source document chunks used to generate answers.

Streamlit UI: Provides a user-friendly interface for file uploads, question input, and response display.

 Architecture

 The application follows a modular architecture with the following components:

Frontend: Streamlit-based UI for user interaction (file upload, question input, and response display).

Backend: PDF Processing: Extracts text using PyPDF2 and splits it into chunks with LangChain's text splitter. Embedding Generation: Generates vector embeddings using Ollama (mxbai-embed-large). Elasticsearch Integration: Stores and retrieves document embeddings for similarity-based search. Conversational AI: Combines LLaMA 3.2 with LangChain's conversational retrieval chain for answering queries.

Memory: Uses LangChain's ConversationBufferMemory to retain chat history.

Minimize image
Edit image
Delete image

Process Flow Diagram


Key Components

LLM: OllamaLLM(model="llama3.2:latest") for generating conversational responses.

Embeddings: OllamaEmbeddings(model="mxbai-embed-large") for vectorizing text chunks.

Elasticsearch: Stores text and embeddings in the pdf_chatbot_index index with a dense vector field (1024 dimensions).

Prompt Template: Custom QA prompt to ensure accurate and context-aware answers.

Memory: ConversationBufferMemory to store chat history and enable follow-up questions.

Retriever: ElasticsearchStore.as_retriever() to fetch the top 3 relevant document chunks based on vector similarity.

Error Handling

UI Errors: Displays errors in the Streamlit UI for issues like failed Elasticsearch connections or query processing errors.

Logging: Uses Python’s logging module to log indexing and connection activities for debugging (vector_embedding.py).

Connection Check: Verifies Elasticsearch connectivity during initialization.

Limitations

Supports only PDF files; other formats (e.g., DOCX, TXT) are not supported.

Requires a local Elasticsearch instance, which may need configuration for production use.

Depends on Ollama for LLM and embeddings, which may have performance or compatibility constraints.

Fixed embedding dimension (1024) based on mxbai-embed-large.

Future Enhancements

Add support for additional document formats (e.g., DOCX, TXT).

Integrate with cloud-hosted Elasticsearch for scalability.

Implement caching for faster query responses.

Enhance the UI with features like multi-file uploads or advanced query options.

Add support for multi-language documents.

Troubleshooting

Elasticsearch Not Running:

Ollama Issues:

Dependency Errors:

PDF Processing Errors

License

This project is provided as-is for educational and personal use. Ensure compliance with the licenses of dependencies (e.g., Streamlit, LangChain, Elasticsearch).

