FROM docker.elastic.co/elasticsearch/elasticsearch:8.6.2

RUN elasticsearch-plugin install --batch analysis-nori

ENV discovery.type=single-node
ENV xpack.security.enabled=false
ENV ES_JAVA_OPTS="-Xms512m -Xmx512m"