// Mesh Verse Doctor is a read-only serial-port preflight helper.
//
// It NEVER opens, transmits to, configures, or resets a radio. It only lists
// likely serial-device paths, checks that explicitly supplied paths exist, and
// prints a safe command line for Mesh Verse's Python bridge.
package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"sort"
	"strings"
)

const version = "0.1.0"

type Port struct {
	Path        string `json:"path"`
	StableAlias bool   `json:"stable_alias"`
	Target      string `json:"target,omitempty"`
	Exists      bool   `json:"exists"`
	CharDevice  bool   `json:"char_device"`
	Mode        string `json:"mode,omitempty"`
}

type Check struct {
	Name    string `json:"name"`
	Status  string `json:"status"` // pass, warn, fail
	Message string `json:"message"`
}

type Report struct {
	Tool       string  `json:"tool"`
	Version    string  `json:"version"`
	Platform   string  `json:"platform"`
	Ports      []Port  `json:"ports"`
	Checks     []Check `json:"checks"`
	Suggestion string  `json:"suggestion,omitempty"`
}

func main() {
	meshtasticPort := flag.String("meshtastic-port", "", "Meshtastic serial path to validate, e.g. /dev/ttyACM0")
	meshcorePort := flag.String("meshcore-port", "", "MeshCore serial path to validate, e.g. /dev/ttyUSB0")
	asJSON := flag.Bool("json", false, "Print machine-readable JSON")
	flag.Parse()

	report := Report{
		Tool:     "meshverse-doctor",
		Version:  version,
		Platform: runtime.GOOS + "/" + runtime.GOARCH,
		Ports:    discoverPorts(),
	}

	report.Checks = append(report.Checks, Check{
		Name:    "read-only-mode",
		Status:  "pass",
		Message: "This tool does not open or write to any serial port.",
	})

	report.Checks = append(report.Checks, validatePair(*meshtasticPort, *meshcorePort)...)
	if *meshtasticPort != "" && *meshcorePort != "" {
		report.Suggestion = suggestedCommand(*meshtasticPort, *meshcorePort)
	}

	if *asJSON {
		encoder := json.NewEncoder(os.Stdout)
		encoder.SetIndent("", "  ")
		if err := encoder.Encode(report); err != nil {
			fmt.Fprintf(os.Stderr, "could not encode JSON: %v\n", err)
			os.Exit(1)
		}
		return
	}

	printHuman(report)
	if anyFail(report.Checks) {
		os.Exit(2)
	}
}

func discoverPorts() []Port {
	var patterns []string
	var stableDirs []string

	switch runtime.GOOS {
	case "linux":
		patterns = []string{
			"/dev/ttyACM*",
			"/dev/ttyUSB*",
			"/dev/ttyAMA*",
			"/dev/ttyS*",
		}
		stableDirs = []string{"/dev/serial/by-id", "/dev/serial/by-path"}
	case "darwin":
		patterns = []string{"/dev/cu.*", "/dev/tty.*"}
	case "windows":
		// Windows does not expose COM ports as ordinary filesystem entries.
		// They are intentionally not guessed here; pass explicit COMx paths
		// to the actual bridge after checking Device Manager.
		return nil
	default:
		return nil
	}

	seen := make(map[string]bool)
	ports := make([]Port, 0)

	for _, pattern := range patterns {
		matches, _ := filepath.Glob(pattern)
		for _, match := range matches {
			if seen[match] {
				continue
			}
			seen[match] = true
			ports = append(ports, inspectPath(match, false))
		}
	}

	for _, dir := range stableDirs {
		entries, err := os.ReadDir(dir)
		if err != nil {
			continue
		}
		for _, entry := range entries {
			alias := filepath.Join(dir, entry.Name())
			if seen[alias] {
				continue
			}
			seen[alias] = true
			ports = append(ports, inspectPath(alias, true))
		}
	}

	sort.Slice(ports, func(i, j int) bool {
		if ports[i].StableAlias != ports[j].StableAlias {
			return ports[i].StableAlias
		}
		return ports[i].Path < ports[j].Path
	})
	return ports
}

func inspectPath(path string, stableAlias bool) Port {
	port := Port{Path: path, StableAlias: stableAlias}

	info, err := os.Stat(path)
	if err != nil {
		return port
	}

	port.Exists = true
	port.CharDevice = info.Mode()&os.ModeCharDevice != 0
	port.Mode = info.Mode().String()

	if stableAlias {
		if target, err := filepath.EvalSymlinks(path); err == nil {
			port.Target = target
		}
	}
	return port
}

func validatePair(meshtasticPort, meshcorePort string) []Check {
	checks := make([]Check, 0, 3)

	if meshtasticPort == "" && meshcorePort == "" {
		return append(checks, Check{
			Name:    "explicit-port-check",
			Status:  "warn",
			Message: "No ports supplied. Use --meshtastic-port and --meshcore-port for a full preflight.",
		})
	}

	if meshtasticPort == "" || meshcorePort == "" {
		return append(checks, Check{
			Name:    "explicit-port-check",
			Status:  "fail",
			Message: "Supply both --meshtastic-port and --meshcore-port together.",
		})
	}

	if pathsEquivalent(meshtasticPort, meshcorePort) {
		return append(checks, Check{
			Name:    "different-radios",
			Status:  "fail",
			Message: "Meshtastic and MeshCore ports point to the same device. The bridge needs two distinct radios.",
		})
	}

	checks = append(checks, validateOne("meshtastic-port", meshtasticPort))
	checks = append(checks, validateOne("meshcore-port", meshcorePort))
	return checks
}

func validateOne(name, path string) Check {
	port := inspectPath(path, false)
	if !port.Exists {
		return Check{
			Name:    name,
			Status:  "fail",
			Message: fmt.Sprintf("%s does not exist. Reconnect the device or check the path.", path),
		}
	}

	if runtime.GOOS != "windows" && !port.CharDevice {
		return Check{
			Name:    name,
			Status:  "warn",
			Message: fmt.Sprintf("%s exists but is not reported as a character device (%s). Verify the path.", path, port.Mode),
		}
	}

	return Check{
		Name:    name,
		Status:  "pass",
		Message: fmt.Sprintf("%s exists (%s).", path, port.Mode),
	}
}

func pathsEquivalent(a, b string) bool {
	cleanA := filepath.Clean(a)
	cleanB := filepath.Clean(b)
	if cleanA == cleanB {
		return true
	}

	resolvedA, errA := filepath.EvalSymlinks(cleanA)
	resolvedB, errB := filepath.EvalSymlinks(cleanB)
	return errA == nil && errB == nil && resolvedA == resolvedB
}

func suggestedCommand(meshtasticPort, meshcorePort string) string {
	return strings.Join([]string{
		"python translator.py \\",
		"  --meshtastic-port " + shellQuote(meshtasticPort) + " \\",
		"  --meshcore-port " + shellQuote(meshcorePort) + " \\",
		"  --dry-run --debug",
	}, "\n")
}

func shellQuote(value string) string {
	if value == "" {
		return "''"
	}
	// Single-quote shell escaping is portable on the Linux hosts this bridge
	// targets. Paths normally have no quotes, but handling them costs little.
	return "'" + strings.ReplaceAll(value, "'", "'\\''") + "'"
}

func printHuman(report Report) {
	fmt.Printf("Mesh Verse Doctor v%s\n", report.Version)
	fmt.Printf("Platform: %s\n", report.Platform)
	fmt.Println("Mode: read-only. No serial port will be opened or written to.")
	fmt.Println()

	fmt.Println("Detected candidate serial paths:")
	if len(report.Ports) == 0 {
		fmt.Println("  (none found)")
		if runtime.GOOS == "windows" {
			fmt.Println("  On Windows, check Device Manager for the COM port number.")
		} else {
			fmt.Println("  Connect both radios, then run this command again.")
		}
	} else {
		for _, port := range report.Ports {
			label := "device"
			if port.StableAlias {
				label = "stable alias"
			}
			target := ""
			if port.Target != "" {
				target = " -> " + port.Target
			}
			fmt.Printf("  [%s] %s%s\n", label, port.Path, target)
		}
	}

	fmt.Println()
	fmt.Println("Preflight:")
	for _, check := range report.Checks {
		fmt.Printf("  [%s] %s: %s\n", strings.ToUpper(check.Status), check.Name, check.Message)
	}

	if report.Suggestion != "" {
		fmt.Println()
		fmt.Println("Suggested first test (no transmission):")
		fmt.Println(report.Suggestion)
	}
}

func anyFail(checks []Check) bool {
	for _, check := range checks {
		if check.Status == "fail" {
			return true
		}
	}
	return false
}
