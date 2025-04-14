from elasticsearch import Elasticsearch
from PyPDF2 import PdfReader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_ollama import OllamaEmbeddings
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class VectorEmbedding:
    def __init__(self, es_host="http://localhost:9200", index_name="pdf_chatbot_index"):
        self.es_client = Elasticsearch(es_host)
        self.index_name = index_name
        self.embedding_model = OllamaEmbeddings(model="mxbai-embed-large")

        if not self.es_client.ping():
            raise ConnectionError(f"Failed to connect to Elasticsearch at {es_host}")

        if not self.es_client.indices.exists(index=self.index_name):
            self._create_index()

    def _create_index(self):
        mapping = {
            "mappings": {
                "properties": {
                    "text": {"type": "text"},
                    "vector": {"type": "dense_vector", "dims": 1024}
                }
            }
        }
        self.es_client.indices.create(index=self.index_name, body=mapping)
        logger.info(f"Index {self.index_name} created")

    def extract_text_from_pdf(self, pdf_file):
        pdf_reader = PdfReader(pdf_file)
        text = ""
        for page in pdf_reader.pages:
            text += page.extract_text() or ""
        return text

    def split_text(self, text):
        splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
        return splitter.split_text(text)

    def get_embeddings(self, texts):
        return self.embedding_model.embed_documents(texts)

    def index_to_elasticsearch(self, chunks, embeddings):
        for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
            doc = {"text": chunk, "vector": embedding}
            self.es_client.index(index=self.index_name, id=f"chunk_{i}", body=doc)
        logger.info(f"Indexed {len(chunks)} chunks")

    def process_pdf(self, pdf_file):
        text = self.extract_text_from_pdf(pdf_file)
        chunks = self.split_text(text)
        embeddings = self.get_embeddings(chunks)
        self.index_to_elasticsearch(chunks, embeddings)
