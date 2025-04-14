##docket install and run command for elastic search.
docker pull docker.elastic.co/elasticsearch/elasticsearch:7.5.2
docker run -d --name elasticsearch -p 9200:9200 -p 9300:9300 -e "discovery.type=single-node" -e "xpack.security.enabled=false" docker.elastic.co/elasticsearch/elasticsearch:8.14.0
##Create new venv
python3 -m venv .venv
source .venv/bin/activate
##install packages from requirements.txt
pip install -r requirements.txt  
llm = OllamaLLM(model="llama3.2:latest", temperature=0.7)
Verify Elasticsearch:
Check if it's running:
bash

curl http://localhost:9200

You should see a JSON response with the cluster name and version.

Stop/Start Container (Optional):
Stop: docker stop elasticsearch

Start: docker start elasticsearch

Remove (if needed): docker rm elasticsearch

streamlit run app.py

curl -X DELETE "localhost:9200/pdf_chatbot_index"

curl -X GET "localhost:9200/pdf_chatbot_index/_mapping?pretty"

pip install --upgrade langchain langchain-community
