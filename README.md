# Otus homework
## Запуск в minikube
```
echo "127.0.0.1 arch.homework" >> /etc/hosts
minikube tunnel
helm upgrade -i otus-chart oci://ghcr.io/nosovdi/otus-chart:1.0.3 -n default
helm upgrade -i otus-apigataway oci://ghcr.io/nosovdi/otus-apigataway-chart:1.0.2 -n default
```
## Исходники Helm chart
https://github.com/nosovdi/otus-hw/tree/main/otus-chart
https://github.com/nosovdi/otus-hw/tree/main/api_gateway/helm-chart

## Postman коллекция для тестов
https://github.com/nosovdi/otus-hw/blob/main/UserService.postman_collection.json
Для тестов ApiGataway https://github.com/nosovdi/otus-hw/blob/main/UserService_with apigataway.postman_collection.json
## Мониторинг
Установить Prometheus командой
```
cd prometheus
helm install prometheus oci://ghcr.io/prometheus-community/charts/prometheus -f values.yaml
```
Установить Grafana командой
```
cd grafana
helm repo add grafana https://grafana.github.io/helm-charts
helm repo update
helm install grafana grafana/grafana -f values.yaml
```
Дашборды:  
Дашборд для ингресса - https://github.com/nosovdi/otus-hw/tree/main/grafana/ingress-dashboard.json
Дашборд для приложения - https://github.com/nosovdi/otus-hw/tree/main/grafana/app-dashboard.json
## Полезные команды
```
docker build --platform linux/arm64,linux/amd64 -t ghcr.io/nosovdi/otus-docker:1.0.7 .
helm push otus-chart-1.0.0.tgz oci://ghcr.io/nosovdi
```