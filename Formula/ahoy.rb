class Ahoy < Formula
  desc "Curses TUI for managing sshuttle VPN tunnel connections"
  homepage "https://github.com/galmasi/ahoy"
  url "https://github.com/galmasi/ahoy/archive/refs/tags/v__VERSION__.tar.gz"
  sha256 "__SHA256__"
  license "MIT"

  depends_on "python@3.12"
  depends_on "sshuttle"

  def install
    bin.install "ahoy.py" => "ahoy"
    (share/"ahoy").install "config.example.json"
  end

  def caveats
    <<~EOS
      To get started, copy the example config and edit it:
        mkdir -p ~/.config/ahoy
        cp #{share}/ahoy/config.example.json ~/.config/ahoy/config.json
        $EDITOR ~/.config/ahoy/config.json
    EOS
  end

  test do
    assert_match "usage", shell_output("#{bin}/ahoy --help 2>&1", 1)
  end
end
