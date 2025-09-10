# Otus homework
## Запуск в minikube
```
echo "127.0.0.1 arch.homework" >> /etc/hosts
minikube tunnel
helm upgrade -i otus-chart oci://ghcr.io/nosovdi/otus-chart:1.0.1
```
## Исходники Helm chart

## Postman коллекция для тестов

## Полезные команды
```
docker build --platform linux/arm64,linux/amd64 -t nosovdi/otus-docker:1.0.4 .
helm push otus-chart-1.0.0.tgz oci://ghcr.io/nosovdi
```