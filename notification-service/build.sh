VERSION=$1
docker build --platform linux/arm64,linux/amd64 -t ghcr.io/nosovdi/notification-service:$VERSION .
docker push ghcr.io/nosovdi/notification-service:$VERSION
helm delete notification-service
sleep 5
helm upgrade -i notification-service -f helm-chart/values.yaml --set image.tag=$VERSION -n default helm-chart