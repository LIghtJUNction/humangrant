use humangrant::config::Config;
use humangrant::db::{Store, SystemClock};
use humangrant::error::{Error, Result};
use humangrant::{App, HttpInput, HttpOutput};
use std::collections::BTreeMap;
use std::io::Read;
use std::path::Path;
use std::sync::Arc;

fn run() -> Result<()> {
    let args: Vec<String> = std::env::args().collect();
    if args.len() < 3 || args.iter().any(|arg| arg == "--help") {
        println!("HumanGrant Protocol 0.1 Draft\n\nUsage:\n  humangrant serve CONFIG.json\n  humangrant account-disable CONFIG.json ACCOUNT\n  humangrant permission-remove CONFIG.json ACCOUNT ACTION RESOURCE\n\nThe latter two commands are local administrator operations. No network backdoor is provided.");
        return Ok(());
    }
    let config = Config::load(Path::new(&args[2]))?;
    let clock = Arc::new(SystemClock);
    match args[1].as_str() {
        "account-disable" if args.len() == 4 => {
            Store::open(&config, clock)?.disable_account(&args[3])?;
            println!("Account disabled. Existing grants no longer authorize access.");
            Ok(())
        }
        "permission-remove" if args.len() == 6 => {
            Store::open(&config, clock)?.remove_entitlement(&args[3], &args[4], &args[5])?;
            println!("Permission removed. Existing grants are checked against the current rights.");
            Ok(())
        }
        "serve" if args.len() == 3 => {
            let mut app = App::new(config.clone(), clock)?;
            let server = tiny_http::Server::http(&config.listen).map_err(|_| Error::internal())?;
            if config.mail.mode == "local" {
                app.store.atomic(|db,_| {
                    db.execute("UPDATE mail_operations SET state='delivery_unknown',transport_updated_at=hg_now() WHERE state='sending'",[])?;
                    Ok(())
                })?;
                while humangrant::mail::spool_local(&mut app.store, &config)? {}
            }
            eprintln!(
                "HumanGrant reference server started; public_origin={}",
                config.public_origin
            );
            for mut request in server.incoming_requests() {
                let method = request.method().as_str().to_string();
                let path = request.url().to_string();
                let source = request
                    .remote_addr()
                    .map(|address| address.ip().to_string())
                    .unwrap_or_else(|| "unknown".into());
                let mut headers = BTreeMap::new();
                let mut duplicate = false;
                for header in request.headers() {
                    let name = header.field.to_string().to_ascii_lowercase();
                    if headers
                        .insert(name, header.value.as_str().to_string())
                        .is_some()
                    {
                        duplicate = true;
                    }
                }
                let mut body = vec![];
                let read = request.as_reader().take(16_385).read_to_end(&mut body);
                let output = if duplicate || read.is_err() {
                    HttpOutput::error(Error::invalid())
                } else {
                    app.handle(HttpInput {
                        method,
                        path,
                        headers,
                        body,
                        source,
                    })
                };
                let mut response =
                    tiny_http::Response::from_data(output.body).with_status_code(output.status);
                for (name, value) in output.headers {
                    if let Ok(header) =
                        tiny_http::Header::from_bytes(name.as_bytes(), value.as_bytes())
                    {
                        response.add_header(header);
                    }
                }
                // No request paths, headers, mail addresses, or response bodies are logged.
                if request.respond(response).is_err() {
                    eprintln!("response_write_failed");
                }
            }
            Ok(())
        }
        _ => Err(Error::invalid()),
    }
}

fn main() {
    if let Err(error) = run() {
        eprintln!("{}: {}", error.error, error.message);
        std::process::exit(1);
    }
}
