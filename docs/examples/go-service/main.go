package main

func main() {
	http.HandleFunc("/health", h)
	http.HandleFunc("/v1/orders", orders)
}

func Orders() {}
