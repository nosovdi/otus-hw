VERSION=$1
docker build --platform linux/arm64,linux/amd64 -t ghcr.io/nosovdi/billing-service:$VERSION .
docker push ghcr.io/nosovdi/billing-service:$VERSION
helm delete billing-service
sleep 5
helm upgrade -i billing-service -f helm-chart/values.yaml --set image.tag=$VERSION -n default helm-chart